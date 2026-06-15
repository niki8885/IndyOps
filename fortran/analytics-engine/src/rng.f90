! Deterministic pseudo-random source for the Monte-Carlo projection.
! Engine: xoshiro256** (Blackman & Vigna) seeded by SplitMix64 from the integer

module rng_mod
    use, intrinsic :: iso_fortran_env, only : real64, int64
    implicit none
    private
    public :: rng_t, rng_seed, rng_uniform, rng_normal

    type :: rng_t
        integer(int64) :: s(4) = 0_int64
        logical :: has_spare = .false.
        real(real64) :: spare = 0.0_real64
    end type rng_t

    real(real64), parameter :: TWO_PI = 6.283185307179586476925287_real64
    real(real64), parameter :: INV_2P53 = 1.0_real64 / 9007199254740992.0_real64  ! 1/2^53

contains

    pure function rotl(x, k) result(r)
        integer(int64), intent(in) :: x
        integer, intent(in) :: k
        integer(int64) :: r
        r = ishftc(x, k)
    end function rotl

    ! SplitMix64
    subroutine splitmix64(state, z)
        integer(int64), intent(inout) :: state
        integer(int64), intent(out) :: z
        state = state + (-7046029254386353131_int64)
        z = state
        z = ieor(z, ishft(z, -30)) * (-4658895280553007687_int64)
        z = ieor(z, ishft(z, -27)) * (-7723592293110705685_int64)
        z = ieor(z, ishft(z, -31))
    end subroutine splitmix64

    subroutine rng_seed(rng, seed)
        type(rng_t), intent(out) :: rng
        integer, intent(in) :: seed
        integer(int64) :: sm
        integer :: i
        sm = int(seed, int64)
        do i = 1, 4
            call splitmix64(sm, rng%s(i))
        end do
        rng%has_spare = .false.
        rng%spare = 0.0_real64
    end subroutine rng_seed

    ! xoshiro256** next 64-bit output
    function next_u64(rng) result(r)
        type(rng_t), intent(inout) :: rng
        integer(int64) :: r, t
        r = rotl(rng%s(2) * 5_int64, 7) * 9_int64
        t = ishft(rng%s(2), 17)
        rng%s(3) = ieor(rng%s(3), rng%s(1))
        rng%s(4) = ieor(rng%s(4), rng%s(2))
        rng%s(2) = ieor(rng%s(2), rng%s(3))
        rng%s(1) = ieor(rng%s(1), rng%s(4))
        rng%s(3) = ieor(rng%s(3), t)
        rng%s(4) = rotl(rng%s(4), 45)
    end function next_u64

    ! Uniform double in [0,1)
    function rng_uniform(rng) result(u)
        type(rng_t), intent(inout) :: rng
        real(real64) :: u
        integer(int64) :: x
        x = next_u64(rng)
        u = real(ishft(x, -11), real64) * INV_2P53
    end function rng_uniform

    ! N(mu, sigma) via Box–Muller
    function rng_normal(rng, mu, sigma) result(z)
        type(rng_t), intent(inout) :: rng
        real(real64), intent(in) :: mu, sigma
        real(real64) :: z, u1, u2, rad
        if (rng%has_spare) then
            rng%has_spare = .false.
            z = mu + sigma * rng%spare
            return
        end if
        u1 = rng_uniform(rng)
        u2 = rng_uniform(rng)
        if (u1 <= 0.0_real64) u1 = INV_2P53
        rad = sqrt(-2.0_real64 * log(u1))
        rng%spare = rad * sin(TWO_PI * u2)
        rng%has_spare = .true.
        z = mu + sigma * (rad * cos(TWO_PI * u2))
    end function rng_normal

end module rng_mod
