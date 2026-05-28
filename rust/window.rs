//! `vrcpilot._native.window`: VRChat window focus / unfocus / foreground /
//! geometry.
//!
//! The PyO3 entry points are platform-agnostic; the real work lives in a
//! per-OS `backend` module (`window_linux.rs` / `window_windows.rs`). Each
//! call releases the GIL (`py.detach`) around the X11 / Win32 round-trip.
//! The Python layer keeps the dispatch shape it always had (resolve_pid ->
//! soft-fail to False/None, Wayland-native warning), and merely forwards to
//! these functions.

use pyo3::prelude::*;
use pyo3::types::PyModule;

#[cfg(target_os = "linux")]
#[path = "window_linux.rs"]
mod backend;

#[cfg(target_os = "windows")]
#[path = "window_windows.rs"]
mod backend;

// vrcpilot only supports Windows and Linux (enforced at `import vrcpilot`),
// so this stub never runs; it only keeps the crate compiling on other hosts.
#[cfg(not(any(target_os = "linux", target_os = "windows")))]
mod backend {
    pub(crate) fn focus(_pid: u32) -> bool {
        false
    }
    pub(crate) fn unfocus(_pid: u32) -> bool {
        false
    }
    pub(crate) fn is_foreground(_pid: u32) -> bool {
        false
    }
    pub(crate) fn window_rect(_pid: u32) -> Option<(i64, i64, i64, i64)> {
        None
    }
}

/// Bring the VRChat window owned by `pid` to the foreground. `False` on any
/// failure (no window, display error).
#[pyfunction]
fn focus_window(py: Python<'_>, pid: u32) -> bool {
    py.detach(|| backend::focus(pid))
}

/// Send the VRChat window owned by `pid` to the bottom of the z-order
/// without transferring input focus. `False` on any failure.
#[pyfunction]
fn unfocus_window(py: Python<'_>, pid: u32) -> bool {
    py.detach(|| backend::unfocus(pid))
}

/// Whether the VRChat window owned by `pid` currently owns the foreground.
#[pyfunction]
fn is_window_foreground(py: Python<'_>, pid: u32) -> bool {
    py.detach(|| backend::is_foreground(pid))
}

/// `(x, y, width, height)` of the VRChat window owned by `pid` in desktop
/// pixels, or `None` when no window is found / the display is unreachable.
#[pyfunction]
fn get_window_rect(py: Python<'_>, pid: u32) -> Option<(i64, i64, i64, i64)> {
    py.detach(|| backend::window_rect(pid))
}

/// Register this submodule's functions on the `window` module object.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(focus_window, m)?)?;
    m.add_function(wrap_pyfunction!(unfocus_window, m)?)?;
    m.add_function(wrap_pyfunction!(is_window_foreground, m)?)?;
    m.add_function(wrap_pyfunction!(get_window_rect, m)?)?;
    Ok(())
}
