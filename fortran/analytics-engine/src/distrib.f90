! Distribution primitives for the Monte-Carlo profit simulator (profit-sim binary).

module distrib_mod
    use, intrinsic :: iso_fortran_env, only : real64
    implicit none
    private
    public :: norm_cdf, quantile_grid_interp

    real(real64), parameter :: SQRT2 = 1.4142135623730950488016887_real64

contains

    elemental function norm_cdf(z) result(p)
        real(real64), intent(in) :: z
        real(real64) :: p
        p = 0.5_real64 * (1.0_real64 + erf(z / SQRT2))
    end function norm_cdf

    pure function quantile_grid_interp(grid, k, u) result(v)
        real(real64), intent(in) :: grid(:)
        integer, intent(in) :: k
        real(real64), intent(in) :: u
        real(real64) :: v, pos, frac
        integer :: lo
        pos = max(0.0_real64, min(1.0_real64, u)) * real(k - 1, real64)
        lo = floor(pos)
        if (lo > k - 2) lo = k - 2
        if (lo < 0) lo = 0
        frac = pos - real(lo, real64)
        v = grid(lo + 1) + frac * (grid(lo + 2) - grid(lo + 1))
    end function quantile_grid_interp

end module distrib_mod
