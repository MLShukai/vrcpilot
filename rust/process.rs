//! VRChat process discovery for `vrcpilot._native.process`.
//!
//! Mirrors the contract of the pure-Python `vrcpilot.process.pid.find_pids`
//! it replaces: enumerate every running `VRChat.exe`, newest first
//! (descending start time). The scan runs with the GIL released so a
//! concurrent Python thread (e.g. a capture loop) is not blocked while it
//! walks the process table -- the direct latency win for the input
//! hot-loop, where `ensure_target` calls this before every key/mouse event.

use std::ffi::OsStr;

use pyo3::prelude::*;
use pyo3::types::PyModule;
use sysinfo::{ProcessesToUpdate, System};

/// VRChat's process name on every supported OS. Under Proton on Linux the
/// client still presents itself as `VRChat.exe`.
const VRCHAT_PROCESS_NAME: &str = "VRChat.exe";

/// Order `(start_time, pid)` pairs newest-first and drop the start times.
///
/// A stable sort on the start time (descending) preserves enumeration
/// order for processes reporting the same coarse (1-second) start time,
/// matching the stable `list.sort` the Python implementation relied on.
fn order_pids(mut pairs: Vec<(u64, i64)>) -> Vec<i64> {
    pairs.sort_by_key(|&(start, _)| std::cmp::Reverse(start));
    pairs.into_iter().map(|(_, pid)| pid).collect()
}

/// Walk the process table for VRChat PIDs. Call with the GIL released.
fn scan() -> Vec<i64> {
    let mut sys = System::new();
    sys.refresh_processes(ProcessesToUpdate::All, true);
    let target = OsStr::new(VRCHAT_PROCESS_NAME);
    let pairs: Vec<(u64, i64)> = sys
        .processes()
        .values()
        .filter(|p| p.name() == target)
        .map(|p| (p.start_time(), i64::from(p.pid().as_u32())))
        .collect();
    order_pids(pairs)
}

/// Return PIDs of every running VRChat process, newest first.
///
/// The heavy process-table walk runs detached from the interpreter (GIL
/// released), so other Python threads keep running while this scans.
#[pyfunction]
fn find_pids(py: Python<'_>) -> Vec<i64> {
    py.detach(scan)
}

/// Register this submodule's functions on the `process` module object.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(find_pids, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::order_pids;

    #[test]
    fn orders_newest_first() {
        assert_eq!(
            order_pids(vec![(100, 1), (300, 2), (200, 3)]),
            vec![2, 3, 1]
        );
    }

    #[test]
    fn stable_for_equal_start_times() {
        // Equal start times keep enumeration order: 1, then 2, then 3.
        assert_eq!(order_pids(vec![(50, 1), (50, 2), (50, 3)]), vec![1, 2, 3]);
    }

    #[test]
    fn empty_input_empty_output() {
        assert!(order_pids(vec![]).is_empty());
    }
}
