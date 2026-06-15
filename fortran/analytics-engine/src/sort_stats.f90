! Statistical primitives

module sort_stats_mod
    use, intrinsic :: iso_fortran_env, only : real64
    use, intrinsic :: ieee_arithmetic, only : ieee_is_nan
    use json_mod, only : nan64
    implicit none
    private
    public :: drop_nan, sort_asc, percentile_linear, quantile_copy, mean_f, std_f, histogram_np

contains

    subroutine drop_nan(x, n, out, m)
        real(real64), intent(in) :: x(:)
        integer, intent(in) :: n
        real(real64), allocatable, intent(out) :: out(:)
        integer, intent(out) :: m
        integer :: i
        m = 0
        do i = 1, n
            if (.not. ieee_is_nan(x(i))) m = m + 1
        end do
        allocate(out(m))
        m = 0
        do i = 1, n
            if (.not. ieee_is_nan(x(i))) then
                m = m + 1
                out(m) = x(i)
            end if
        end do
    end subroutine drop_nan

    recursive subroutine sort_asc(a, lo, hi)
        real(real64), intent(inout) :: a(:)
        integer, intent(in) :: lo, hi
        integer :: i, j
        real(real64) :: pivot, tmp
        if (lo >= hi) return
        i = lo
        j = hi
        pivot = a((lo + hi) / 2)
        do
            do while (a(i) < pivot)
                i = i + 1
            end do
            do while (a(j) > pivot)
                j = j - 1
            end do
            if (i <= j) then
                tmp = a(i); a(i) = a(j); a(j) = tmp
                i = i + 1
                j = j - 1
            end if
            if (i > j) exit
        end do
        if (lo < j) call sort_asc(a, lo, j)
        if (i < hi) call sort_asc(a, i, hi)
    end subroutine sort_asc

    function percentile_linear(xs, n, q) result(r)
        real(real64), intent(in) :: xs(:)
        integer, intent(in) :: n
        real(real64), intent(in) :: q
        real(real64) :: r, h, frac
        integer :: lo
        if (n <= 0) then
            r = nan64()
            return
        end if
        if (n == 1) then
            r = xs(1)
            return
        end if
        h = (real(n, real64) - 1.0_real64) * q / 100.0_real64
        lo = floor(h)
        frac = h - real(lo, real64)
        if (lo + 1 >= n) then
            r = xs(n)
        else
            r = xs(lo + 1) + frac * (xs(lo + 2) - xs(lo + 1))
        end if
    end function percentile_linear

    function quantile_copy(x, n, q) result(r)
        real(real64), intent(in) :: x(:)
        integer, intent(in) :: n
        real(real64), intent(in) :: q
        real(real64) :: r
        real(real64), allocatable :: c(:)
        if (n <= 0) then
            r = nan64()
            return
        end if
        allocate(c(n))
        c = x(1:n)
        call sort_asc(c, 1, n)
        r = percentile_linear(c, n, q)
    end function quantile_copy

    function mean_f(x, n) result(m)
        real(real64), intent(in) :: x(:)
        integer, intent(in) :: n
        real(real64) :: m
        if (n <= 0) then
            m = nan64()
            return
        end if
        m = sum(x(1:n)) / real(n, real64)
    end function mean_f

    ! Standard deviation

    function std_f(x, n, ddof) result(s)
        real(real64), intent(in) :: x(:)
        integer, intent(in) :: n
        integer, intent(in) :: ddof
        real(real64) :: s, m, acc
        integer :: i
        if (n - ddof <= 0) then
            s = nan64()
            return
        end if
        m = mean_f(x, n)
        acc = 0.0_real64
        do i = 1, n
            acc = acc + (x(i) - m)**2
        end do
        s = sqrt(acc / real(n - ddof, real64))
    end function std_f

    subroutine histogram_np(x, n, nbins, counts, edges)
        real(real64), intent(in) :: x(:)
        integer, intent(in) :: n, nbins
        integer, allocatable, intent(out) :: counts(:)
        real(real64), allocatable, intent(out) :: edges(:)
        real(real64) :: mn, mx, norm, v
        integer :: i, k, b
        allocate(counts(nbins))
        allocate(edges(nbins + 1))
        counts = 0
        mn = minval(x(1:n))
        mx = maxval(x(1:n))
        if (mn == mx) then
            mn = mn - 0.5_real64
            mx = mx + 0.5_real64
        end if
        do k = 1, nbins + 1
            edges(k) = mn + (mx - mn) * real(k - 1, real64) / real(nbins, real64)
        end do
        norm = real(nbins, real64) / (mx - mn)
        do i = 1, n
            v = x(i)
            b = int((v - mn) * norm)
            if (b == nbins) b = nbins - 1
            if (b < 0) b = 0
            if (b > nbins - 1) b = nbins - 1
            if (v < edges(b + 1)) b = b - 1
            if (b < 0) b = 0
            if (b < nbins - 1) then
                if (v >= edges(b + 2)) b = b + 1
            end if
            if (b > nbins - 1) b = nbins - 1
            counts(b + 1) = counts(b + 1) + 1
        end do
    end subroutine histogram_np

end module sort_stats_mod
