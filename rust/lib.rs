//! Native (Rust/PyO3) backend for the `vrcpilot` Python package.
//!
//! This crate compiles to the private extension module `vrcpilot._native`,
//! whose submodules back the latency-critical paths of vrcpilot:
//!
//! - `process` -- VRChat PID discovery (`find_pids` et al.)
//! - `window`  -- focus / unfocus / foreground checks / window geometry
//! - `capture` -- Linux X11 frame capture
//! - `speaker` -- per-process audio capture + routing
//!
//! Phase 0 ships only the empty scaffold: the module and its submodules
//! import cleanly but expose no functions yet. Each submodule is filled in
//! by its respective workstream. The Python layer keeps its public API and
//! ABCs unchanged and merely delegates the heavy work here.

use pyo3::prelude::*;
use pyo3::types::PyModule;

mod process;
mod window;

/// Create a child module, attach it to `parent` as an attribute, and
/// register it in `sys.modules` under its fully-qualified name.
///
/// Registering in `sys.modules` lets both attribute access
/// (`_native.process`) and the statement form (`import
/// vrcpilot._native.process`) resolve to the same module object. The
/// Python wrappers use attribute access; the `sys.modules` entry is a
/// safety net so neither form surprises callers.
fn add_submodule<'py>(parent: &Bound<'py, PyModule>, name: &str) -> PyResult<Bound<'py, PyModule>> {
    let py = parent.py();
    let child = PyModule::new(py, name)?;
    parent.add(name, &child)?;
    let qualified = format!("vrcpilot._native.{name}");
    py.import("sys")?
        .getattr("modules")?
        .set_item(qualified, &child)?;
    Ok(child)
}

/// Entry point for the `vrcpilot._native` extension module.
///
/// The function name (`_native`) must match `module-name` in
/// `[tool.maturin]`.
#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let process = add_submodule(m, "process")?;
    process::register(&process)?;
    let window = add_submodule(m, "window")?;
    window::register(&window)?;
    add_submodule(m, "capture")?;
    add_submodule(m, "speaker")?;
    Ok(())
}
