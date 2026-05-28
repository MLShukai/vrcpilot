//! Linux (X11/XWayland) window backend for `vrcpilot._native.window`.
//!
//! Reimplements, against x11rb, the EWMH window operations previously done
//! through python-xlib in `vrcpilot.window.linux` and `vrcpilot.geometry`:
//! locate the VRChat top-level via `_NET_CLIENT_LIST` + `_NET_WM_PID`, then
//! activate / lower / query-foreground / read-geometry. Every entry point
//! degrades to `false` / `None` on a missing display, missing window, or X
//! error -- it never panics into Python. The Wayland-native short-circuit
//! and its `RuntimeWarning` stay in the Python layer (`vrcpilot.window`).

use x11rb::connection::Connection;
use x11rb::protocol::xproto::{
    AtomEnum, ClientMessageEvent, ConfigureWindowAux, ConnectionExt, EventMask, StackMode, Window,
};
use x11rb::rust_connection::RustConnection;

/// Connect to the X server named by `$DISPLAY`, returning `(conn, root)`.
///
/// `None` on any connection failure (DISPLAY unset / malformed / server
/// unreachable / stale XAUTHORITY) -- the same soft-failure surface the
/// python-xlib `open_x11_display` had.
fn connect() -> Option<(RustConnection, Window)> {
    let (conn, screen_num) = x11rb::connect(None).ok()?;
    let root = conn.setup().roots[screen_num].root;
    Some((conn, root))
}

/// Resolve a named atom, or `None` on any X failure.
fn atom(conn: &RustConnection, name: &[u8]) -> Option<u32> {
    conn.intern_atom(false, name)
        .ok()?
        .reply()
        .ok()
        .map(|r| r.atom)
}

/// Find the EWMH top-level window owned by `pid` via `_NET_CLIENT_LIST` +
/// `_NET_WM_PID`. Windows that vanish between the snapshot and the property
/// read are skipped (race against the WM during teardown).
fn find_window(conn: &RustConnection, root: Window, pid: u32) -> Option<Window> {
    let net_client_list = atom(conn, b"_NET_CLIENT_LIST")?;
    let net_wm_pid = atom(conn, b"_NET_WM_PID")?;
    let reply = conn
        .get_property(false, root, net_client_list, AtomEnum::ANY, 0, u32::MAX)
        .ok()?
        .reply()
        .ok()?;
    for wid in reply.value32()? {
        let Ok(cookie) = conn.get_property(false, wid, net_wm_pid, AtomEnum::CARDINAL, 0, 1) else {
            continue;
        };
        let Ok(prop) = cookie.reply() else { continue };
        if prop.value32().and_then(|mut v| v.next()) == Some(pid) {
            return Some(wid);
        }
    }
    None
}

pub(crate) fn focus(pid: u32) -> bool {
    let Some((conn, root)) = connect() else {
        return false;
    };
    let Some(window) = find_window(&conn, root, pid) else {
        return false;
    };
    let Some(net_active) = atom(&conn, b"_NET_ACTIVE_WINDOW") else {
        return false;
    };
    // EWMH _NET_ACTIVE_WINDOW request: data[0]=2 (source: pager/automation
    // tool), data[1]=0 (CurrentTime), remaining slots 0.
    let event = ClientMessageEvent::new(32, window, net_active, [2u32, 0, 0, 0, 0]);
    let mask = EventMask::SUBSTRUCTURE_REDIRECT | EventMask::SUBSTRUCTURE_NOTIFY;
    if conn.send_event(false, root, mask, event).is_err() {
        return false;
    }
    conn.flush().is_ok()
}

pub(crate) fn unfocus(pid: u32) -> bool {
    let Some((conn, root)) = connect() else {
        return false;
    };
    let Some(window) = find_window(&conn, root, pid) else {
        return false;
    };
    // ConfigureWindow with stack_mode=Below lowers the window without
    // changing input focus -- the X11 analogue of
    // SetWindowPos(HWND_BOTTOM, SWP_NOACTIVATE).
    let aux = ConfigureWindowAux::new().stack_mode(StackMode::BELOW);
    if conn.configure_window(window, &aux).is_err() {
        return false;
    }
    conn.flush().is_ok()
}

pub(crate) fn is_foreground(pid: u32) -> bool {
    let Some((conn, root)) = connect() else {
        return false;
    };
    let Some(window) = find_window(&conn, root, pid) else {
        return false;
    };
    let Some(net_active) = atom(&conn, b"_NET_ACTIVE_WINDOW") else {
        return false;
    };
    let Ok(cookie) = conn.get_property(false, root, net_active, AtomEnum::ANY, 0, 1) else {
        return false;
    };
    let Ok(prop) = cookie.reply() else {
        return false;
    };
    prop.value32().and_then(|mut v| v.next()) == Some(window)
}

pub(crate) fn window_rect(pid: u32) -> Option<(i64, i64, i64, i64)> {
    let (conn, root) = connect()?;
    let window = find_window(&conn, root, pid)?;
    // python-xlib's `window.translate_coords(root, 0, 0)` issues
    // TranslateCoordinates(src=root, dst=window), yielding root's origin in
    // window space (the negation of the window's position), which the
    // Python code negates back. Here we translate the other direction
    // (src=window, dst=root), so the reply is already the window's true
    // root position -- identical to the Python result, with no negation.
    let coords = conn
        .translate_coordinates(window, root, 0, 0)
        .ok()?
        .reply()
        .ok()?;
    let geom = conn.get_geometry(window).ok()?.reply().ok()?;
    let width = i64::from(geom.width);
    let height = i64::from(geom.height);
    if width <= 0 || height <= 0 {
        return None;
    }
    Some((
        i64::from(coords.dst_x),
        i64::from(coords.dst_y),
        width,
        height,
    ))
}
