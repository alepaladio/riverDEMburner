import numpy as np


def smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def feather_weights(offset_abs, half_width_m, feather_width_m):
    """
    offset_abs: 1D array of |offset| from the corridor centerline.
    feather_width_m: 0 -> hard edge (weight=1 inside, 0 outside).
    Otherwise: weight smoothly goes from 1 to 0 over the last
    feather_width_m meters inside the corridor.
    """
    if feather_width_m <= 0:
        return (offset_abs <= half_width_m).astype(float)

    inner = max(half_width_m - feather_width_m, 0.0)
    w = np.ones_like(offset_abs, dtype=float)
    edge = offset_abs > inner
    t = (half_width_m - offset_abs[edge]) / feather_width_m
    w[edge] = smoothstep(t)
    w[offset_abs > half_width_m] = 0.0
    return w