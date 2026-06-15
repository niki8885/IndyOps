! Technical indicators

module indicators_mod
    use, intrinsic :: iso_fortran_env, only : real64
    use, intrinsic :: ieee_arithmetic, only : ieee_is_nan
    use json_mod, only : nan64
    implicit none
    private
    public :: indicators_t, compute_indicators

    type :: indicators_t
        real(real64), allocatable :: sma(:), std(:), ema(:), bb_upper(:), bb_lower(:)
        real(real64), allocatable :: returns(:), volatility(:)
        real(real64), allocatable :: rsi(:), macd(:), macd_signal(:), macd_hist(:)
        real(real64), allocatable :: tenkan(:), kijun(:), senkou_a(:), senkou_b(:)
    end type indicators_t

contains

    ! rolling mean, min_periods
    function roll_mean(x, n, win) result(o)
        real(real64), intent(in) :: x(:)
        integer, intent(in) :: n, win
        real(real64), allocatable :: o(:)
        integer :: i, j
        logical :: bad
        allocate(o(n))
        do i = 1, n
            if (i < win) then
                o(i) = nan64()
                cycle
            end if
            bad = .false.
            do j = i - win + 1, i
                if (ieee_is_nan(x(j))) then
                    bad = .true.
                    exit
                end if
            end do
            if (bad) then
                o(i) = nan64()
            else
                o(i) = sum(x(i - win + 1:i)) / real(win, real64)
            end if
        end do
    end function roll_mean

    ! rolling sample std (ddof), min_periods
    function roll_std(x, n, win, ddof) result(o)
        real(real64), intent(in) :: x(:)
        integer, intent(in) :: n, win, ddof
        real(real64), allocatable :: o(:)
        integer :: i, j
        logical :: bad
        real(real64) :: m, acc
        allocate(o(n))
        do i = 1, n
            if (i < win .or. win - ddof <= 0) then
                o(i) = nan64()
                cycle
            end if
            bad = .false.
            do j = i - win + 1, i
                if (ieee_is_nan(x(j))) then
                    bad = .true.
                    exit
                end if
            end do
            if (bad) then
                o(i) = nan64()
                cycle
            end if
            m = sum(x(i - win + 1:i)) / real(win, real64)
            acc = 0.0_real64
            do j = i - win + 1, i
                acc = acc + (x(j) - m)**2
            end do
            o(i) = sqrt(acc / real(win - ddof, real64))
        end do
    end function roll_std

    ! exponentially weighted mean
    function ewm_af(x, n, span) result(o)
        real(real64), intent(in) :: x(:)
        integer, intent(in) :: n, span
        real(real64), allocatable :: o(:)
        real(real64) :: alpha
        integer :: i
        allocate(o(n))
        if (n == 0) return
        alpha = 2.0_real64 / (real(span, real64) + 1.0_real64)
        o(1) = x(1)
        do i = 2, n
            o(i) = alpha * x(i) + (1.0_real64 - alpha) * o(i - 1)
        end do
    end function ewm_af

    function pct_change(x, n) result(o)
        real(real64), intent(in) :: x(:)
        integer, intent(in) :: n
        real(real64), allocatable :: o(:)
        integer :: i
        allocate(o(n))
        if (n == 0) return
        o(1) = nan64()
        do i = 2, n
            o(i) = x(i) / x(i - 1) - 1.0_real64
        end do
    end function pct_change

    function diff_arr(x, n) result(o)
        real(real64), intent(in) :: x(:)
        integer, intent(in) :: n
        real(real64), allocatable :: o(:)
        integer :: i
        allocate(o(n))
        if (n == 0) return
        o(1) = nan64()
        do i = 2, n
            o(i) = x(i) - x(i - 1)
        end do
    end function diff_arr

    function roll_max(x, n, win) result(o)
        real(real64), intent(in) :: x(:)
        integer, intent(in) :: n, win
        real(real64), allocatable :: o(:)
        integer :: i
        allocate(o(n))
        do i = 1, n
            if (i < win) then
                o(i) = nan64()
            else
                o(i) = maxval(x(i - win + 1:i))
            end if
        end do
    end function roll_max

    function roll_min(x, n, win) result(o)
        real(real64), intent(in) :: x(:)
        integer, intent(in) :: n, win
        real(real64), allocatable :: o(:)
        integer :: i
        allocate(o(n))
        do i = 1, n
            if (i < win) then
                o(i) = nan64()
            else
                o(i) = minval(x(i - win + 1:i))
            end if
        end do
    end function roll_min

    ! pandas Series.shift(k): out(i) = x(i-k), first k entries NaN.
    function shift_arr(x, n, k) result(o)
        real(real64), intent(in) :: x(:)
        integer, intent(in) :: n, k
        real(real64), allocatable :: o(:)
        integer :: i
        allocate(o(n))
        do i = 1, n
            if (i <= k) then
                o(i) = nan64()
            else
                o(i) = x(i - k)
            end if
        end do
    end function shift_arr

    subroutine compute_indicators(price, n, window, ind)
        real(real64), intent(in) :: price(:)
        integer, intent(in) :: n, window
        type(indicators_t), intent(out) :: ind
        integer :: win, i
        real(real64), allocatable :: delta(:), up(:), down(:), up_ma(:), down_ma(:), rs(:)
        real(real64), allocatable :: ema12(:), ema26(:), hi(:), lo(:)

        win = max(2, window)

        ind%sma = roll_mean(price, n, win)
        ind%std = roll_std(price, n, win, 1)
        ind%ema = ewm_af(price, n, win)
        allocate(ind%bb_upper(n), ind%bb_lower(n))
        ind%bb_upper = ind%sma + 2.0_real64 * ind%std
        ind%bb_lower = ind%sma - 2.0_real64 * ind%std

        ind%returns = pct_change(price, n)
        ind%volatility = roll_std(ind%returns, n, win, 1)

        ! RSI(14)
        delta = diff_arr(price, n)
        allocate(up(n), down(n))
        do i = 1, n
            if (ieee_is_nan(delta(i))) then
                up(i) = nan64()
                down(i) = nan64()
            else
                up(i) = max(delta(i), 0.0_real64)
                down(i) = max(-delta(i), 0.0_real64)
            end if
        end do
        up_ma = roll_mean(up, n, 14)
        down_ma = roll_mean(down, n, 14)
        allocate(rs(n), ind%rsi(n))
        do i = 1, n
            rs(i) = up_ma(i) / down_ma(i)                       ! IEEE: /0 → inf, 0/0 → NaN
            ind%rsi(i) = 100.0_real64 - 100.0_real64 / (1.0_real64 + rs(i))
        end do

        ! MACD(12/26/9)
        ema12 = ewm_af(price, n, 12)
        ema26 = ewm_af(price, n, 26)
        allocate(ind%macd(n))
        ind%macd = ema12 - ema26
        ind%macd_signal = ewm_af(ind%macd, n, 9)
        allocate(ind%macd_hist(n))
        ind%macd_hist = ind%macd - ind%macd_signal

        ! Ichimoku(9/26/52)
        allocate(ind%tenkan(n), ind%kijun(n))
        ind%tenkan = (roll_max(price, n, 9) + roll_min(price, n, 9)) / 2.0_real64
        ind%kijun = (roll_max(price, n, 26) + roll_min(price, n, 26)) / 2.0_real64
        ind%senkou_a = shift_arr((ind%tenkan + ind%kijun) / 2.0_real64, n, 26)
        hi = roll_max(price, n, 52)
        lo = roll_min(price, n, 52)
        ind%senkou_b = shift_arr((hi + lo) / 2.0_real64, n, 26)
    end subroutine compute_indicators

end module indicators_mod
