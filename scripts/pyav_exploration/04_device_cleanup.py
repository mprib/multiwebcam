#!/usr/bin/env python3
"""
Script 04: Device Cleanup

Verify proper resource cleanup, context managers, and error recovery.
Checks for file descriptor leaks after rapid open/close cycles.

Usage:
    uv run python scripts/pyav_exploration/04_device_cleanup.py [device]
"""

import os
import sys

import av


def count_fds() -> int:
    """Count open file descriptors for current process."""
    return len(os.listdir("/proc/self/fd"))


def test_rapid_open_close(device: str, cycles: int = 10) -> bool:
    """
    Test rapid open/close cycles for fd leaks.

    Opens and closes the device multiple times, grabbing one frame each time.
    Compares fd count before and after to detect leaks.
    """
    print(f"\nTest 1: Rapid open/close ({cycles} cycles)...")

    initial_fds = count_fds()

    for i in range(cycles):
        container = av.open(device, format="v4l2")
        # Grab one frame to ensure device is fully initialized
        frame = next(container.decode(video=0))
        container.close()
        print(f"  Cycle {i + 1}/{cycles}: grabbed frame {frame.width}x{frame.height}")

    final_fds = count_fds()
    leaked = final_fds - initial_fds

    if leaked > 0:
        print(f"  FAIL: {leaked} file descriptor(s) leaked")
        return False

    print(f"  OK: No fd leaks (initial={initial_fds}, final={final_fds})")
    return True


def test_context_manager(device: str) -> bool:
    """
    Test context manager pattern for automatic cleanup.

    Verifies that 'with' statement properly closes the container.
    """
    print("\nTest 2: Context manager pattern...")

    initial_fds = count_fds()

    with av.open(device, format="v4l2") as container:
        frame = next(container.decode(video=0))
        print(f"  Inside context: grabbed frame {frame.width}x{frame.height}")

    # Container should be closed here
    final_fds = count_fds()
    leaked = final_fds - initial_fds

    if leaked > 0:
        print(f"  FAIL: {leaked} file descriptor(s) leaked after context exit")
        return False

    print(f"  OK: Context manager closed properly (initial={initial_fds}, final={final_fds})")
    return True


def test_error_recovery(device: str) -> bool:
    """
    Test cleanup after error during capture.

    Simulates an error path and verifies resources are still released.
    """
    print("\nTest 3: Error recovery (simulated exception)...")

    initial_fds = count_fds()

    try:
        container = av.open(device, format="v4l2")
        frame = next(container.decode(video=0))
        print(f"  Opened device, grabbed frame {frame.width}x{frame.height}")

        # Simulate an error
        raise RuntimeError("Simulated error during capture")
    except RuntimeError as e:
        print(f"  Caught expected error: {e}")
    finally:
        # Explicit cleanup in finally block
        if "container" in dir() and container is not None:
            container.close()
            print("  Closed container in finally block")

    final_fds = count_fds()
    leaked = final_fds - initial_fds

    if leaked > 0:
        print(f"  FAIL: {leaked} file descriptor(s) leaked after error recovery")
        return False

    print(f"  OK: Cleanup after error successful (initial={initial_fds}, final={final_fds})")
    return True


def test_context_manager_with_error(device: str) -> bool:
    """
    Test context manager cleanup after exception inside 'with' block.

    This is the recommended pattern - context manager handles cleanup
    even when exceptions occur.
    """
    print("\nTest 4: Context manager with exception...")

    initial_fds = count_fds()

    try:
        with av.open(device, format="v4l2") as container:
            frame = next(container.decode(video=0))
            print(f"  Inside context: grabbed frame {frame.width}x{frame.height}")
            raise RuntimeError("Simulated error inside context")
    except RuntimeError as e:
        print(f"  Caught expected error: {e}")

    # Context manager should have closed despite exception
    final_fds = count_fds()
    leaked = final_fds - initial_fds

    if leaked > 0:
        print(f"  FAIL: {leaked} file descriptor(s) leaked after exception in context")
        return False

    print(f"  OK: Context manager cleaned up after exception (initial={initial_fds}, final={final_fds})")
    return True


def test_reopen_after_close(device: str) -> bool:
    """
    Test that device can be reopened immediately after close.

    Checks for "device busy" errors that indicate incomplete cleanup.
    """
    print("\nTest 5: Reopen immediately after close...")

    # First open/close
    container1 = av.open(device, format="v4l2")
    frame1 = next(container1.decode(video=0))
    print(f"  First open: grabbed frame {frame1.width}x{frame1.height}")
    container1.close()
    print("  First close completed")

    # Immediate reopen - should not get "device busy"
    try:
        container2 = av.open(device, format="v4l2")
        frame2 = next(container2.decode(video=0))
        print(f"  Second open: grabbed frame {frame2.width}x{frame2.height}")
        container2.close()
        print("  Second close completed")
    except av.AVError as e:
        if "busy" in str(e).lower():
            print(f"  FAIL: Device busy on reopen - previous handle not fully released")
            print(f"  Error: {e}")
            return False
        raise

    print("  OK: Device reopened successfully after close")
    return True


def main():
    device = sys.argv[1] if len(sys.argv) > 1 else "/dev/video0"

    print("=" * 70)
    print("PyAV Exploration - Script 04: Device Cleanup")
    print("=" * 70)
    print(f"\nDevice: {device}")
    print(f"Initial fd count: {count_fds()}")

    results = []

    # Run all tests
    results.append(("Rapid open/close", test_rapid_open_close(device)))
    results.append(("Context manager", test_context_manager(device)))
    results.append(("Error recovery", test_error_recovery(device)))
    results.append(("Context manager with error", test_context_manager_with_error(device)))
    results.append(("Reopen after close", test_reopen_after_close(device)))

    # Summary
    print("\n" + "=" * 70)
    print("Summary:")
    print("=" * 70)

    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("All cleanup tests passed!")
    else:
        print("Some tests failed - investigate fd leaks or cleanup issues")

    print(f"\nFinal fd count: {count_fds()}")

    print("\n" + "=" * 70)
    print("Key Findings:")
    print("=" * 70)
    print("""
1. PyAV containers support context manager protocol
2. Use 'with' statement for automatic cleanup on both normal and error paths
3. Explicit close() works but requires try/finally for error safety
4. No delay needed between close and reopen

Recommended pattern:
    with av.open(device, format='v4l2') as container:
        for frame in container.decode(video=0):
            # process frame
            ...
""")


if __name__ == "__main__":
    main()
