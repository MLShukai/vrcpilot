//! Windows (Win32) window backend for `vrcpilot._native.window`.
//!
//! IMPLEMENTED BUT UNVERIFIED ON THE LINUX DEV BOX: this file is compiled
//! only on Windows (`#[cfg(target_os = "windows")]` in `window.rs`), so the
//! Linux CI/dev loop cannot type-check or run it. A Windows machine runs the
//! verify/fix loop -- see `docs/windows-native-verification.md`.
//!
//! Mirrors `vrcpilot.window.windows` + `vrcpilot.windows.get_window_rect`:
//! locate the visible top-level HWND owned by `pid` via EnumWindows, then
//! SetForegroundWindow / SetWindowPos(HWND_BOTTOM) / GetForegroundWindow /
//! GetWindowRect (per-monitor-DPI-aware V2). Soft-fails to false / None.

use windows::core::BOOL;
use windows::Win32::Foundation::{HWND, LPARAM, RECT, TRUE};
use windows::Win32::UI::HiDpi::{
    SetThreadDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
};
use windows::Win32::UI::Input::KeyboardAndMouse::{
    keybd_event, KEYBD_EVENT_FLAGS, KEYEVENTF_KEYUP, VK_MENU,
};
use windows::Win32::UI::WindowsAndMessaging::{
    BringWindowToTop, EnumWindows, GetForegroundWindow, GetWindowRect, GetWindowThreadProcessId,
    IsIconic, IsWindowVisible, SetForegroundWindow, SetWindowPos, ShowWindow, HWND_BOTTOM,
    SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE, SW_RESTORE,
};

/// Collector handed to the EnumWindows callback via `LPARAM`.
struct FindCtx {
    pid: u32,
    found: Option<HWND>,
}

/// EnumWindows callback: record the first visible top-level owned by `pid`.
///
/// Always returns `TRUE` (continue enumeration). Returning `FALSE` makes
/// Win32 treat the callback as failed and surfaces GetLastError; the prior
/// pywin32 code enumerated fully and took the first match, so we do too.
unsafe extern "system" fn enum_proc(hwnd: HWND, lparam: LPARAM) -> BOOL {
    let ctx = &mut *(lparam.0 as *mut FindCtx);
    if ctx.found.is_some() {
        return TRUE;
    }
    let mut found_pid: u32 = 0;
    GetWindowThreadProcessId(hwnd, Some(&mut found_pid));
    if found_pid == ctx.pid && IsWindowVisible(hwnd).as_bool() {
        ctx.found = Some(hwnd);
    }
    TRUE
}

/// Locate the visible top-level HWND owned by `pid`, or `None`.
fn find_hwnd(pid: u32) -> Option<HWND> {
    let mut ctx = FindCtx { pid, found: None };
    unsafe {
        // The callback never returns FALSE, so EnumWindows returns Ok; read
        // the collector regardless.
        let _ = EnumWindows(Some(enum_proc), LPARAM(&mut ctx as *mut FindCtx as isize));
    }
    ctx.found
}

pub(crate) fn focus(pid: u32) -> bool {
    let Some(hwnd) = find_hwnd(pid) else {
        return false;
    };
    unsafe {
        if IsIconic(hwnd).as_bool() {
            let _ = ShowWindow(hwnd, SW_RESTORE);
        }
        // Press/release Alt to defeat the SetForegroundWindow lock: without
        // a fresh input event from this process the OS may refuse the
        // foreground change.
        keybd_event(VK_MENU.0 as u8, 0, KEYBD_EVENT_FLAGS(0), 0);
        let _ = SetForegroundWindow(hwnd);
        let brought = BringWindowToTop(hwnd);
        keybd_event(VK_MENU.0 as u8, 0, KEYEVENTF_KEYUP, 0);
        brought.is_ok()
    }
}

pub(crate) fn unfocus(pid: u32) -> bool {
    let Some(hwnd) = find_hwnd(pid) else {
        return false;
    };
    unsafe {
        SetWindowPos(
            hwnd,
            Some(HWND_BOTTOM),
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
        .is_ok()
    }
}

pub(crate) fn is_foreground(pid: u32) -> bool {
    let Some(hwnd) = find_hwnd(pid) else {
        return false;
    };
    unsafe { GetForegroundWindow() == hwnd }
}

pub(crate) fn window_rect(pid: u32) -> Option<(i64, i64, i64, i64)> {
    let hwnd = find_hwnd(pid)?;
    unsafe {
        // Per-monitor-DPI-aware V2 so GetWindowRect reports physical pixels
        // (matching the capture path); restored on exit (thread-local).
        let old = SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        let mut rect = RECT::default();
        let got = GetWindowRect(hwnd, &mut rect);
        SetThreadDpiAwarenessContext(old);
        got.ok()?;
        let width = i64::from(rect.right - rect.left);
        let height = i64::from(rect.bottom - rect.top);
        if width <= 0 || height <= 0 {
            return None;
        }
        Some((i64::from(rect.left), i64::from(rect.top), width, height))
    }
}
