module json_mod
    use, intrinsic :: iso_fortran_env, only : real64
    use, intrinsic :: ieee_arithmetic, only : ieee_value, ieee_quiet_nan, ieee_is_finite
    implicit none
    private

    public :: nan64
    ! reading
    public :: key_pos, get_int_or, get_f64_scalar, get_f64_array, get_int_array
    ! writing
    public :: jbuilder, jb_init, jb_push, jb_str, jb_f64, jb_int, jb_f64_array, jb_int_array

    type :: jbuilder
        character(len = :), allocatable :: s
        integer :: n = 0
    end type jbuilder

contains

    ! shared

    function nan64() result(x)
        real(real64) :: x
        x = ieee_value(1.0_real64, ieee_quiet_nan)
    end function nan64

    ! reading

    function key_pos(buf, key) result(p)
        character(len = *), intent(in) :: buf, key
        integer :: p, kp, cp, i
        p = 0
        kp = index(buf, '"' // key // '"')
        if (kp == 0) return
        cp = index(buf(kp:), ':')
        if (cp == 0) return
        i = kp + cp
        do while (i <= len(buf))
            select case (buf(i:i))
            case (' ', char(9), char(10), char(13))
                i = i + 1
            case default
                exit
            end select
        end do
        p = i
    end function key_pos

    function scalar_token(buf, start) result(tok)
        character(len = *), intent(in) :: buf
        integer, intent(in) :: start
        character(len = :), allocatable :: tok
        integer :: j
        j = start
        do while (j <= len(buf))
            select case (buf(j:j))
            case (',', '}', ']')
                exit
            case default
                j = j + 1
            end select
        end do
        tok = trim(adjustl(buf(start:j - 1)))
    end function scalar_token

    function get_int_or(buf, key, default) result(v)
        character(len = *), intent(in) :: buf, key
        integer, intent(in) :: default
        integer :: v, p, ios
        character(len = :), allocatable :: tok
        v = default
        p = key_pos(buf, key)
        if (p == 0) return
        tok = scalar_token(buf, p)
        if (tok == 'null' .or. len(tok) == 0) return
        read(tok, *, iostat = ios) v
        if (ios /= 0) v = default
    end function get_int_or

    subroutine get_f64_scalar(buf, key, val, found)
        character(len = *), intent(in) :: buf, key
        real(real64), intent(out) :: val
        logical, intent(out) :: found
        integer :: p, ios
        character(len = :), allocatable :: tok
        val = nan64()
        found = .false.
        p = key_pos(buf, key)
        if (p == 0) return
        found = .true.
        tok = scalar_token(buf, p)
        if (tok == 'null' .or. len(tok) == 0) return
        read(tok, *, iostat = ios) val
        if (ios /= 0) val = nan64()
    end subroutine get_f64_scalar

    subroutine array_inner(buf, key, inner, n, ok)
        character(len = *), intent(in) :: buf, key
        character(len = :), allocatable, intent(out) :: inner
        integer, intent(out) :: n
        logical, intent(out) :: ok
        integer :: p, q, i
        n = 0
        ok = .false.
        inner = ''
        p = key_pos(buf, key)
        if (p == 0) return
        q = index(buf(p:), ']')
        if (q == 0) return
        ok = .true.
        q = p + q - 1
        inner = buf(p + 1:q - 1)
        if (len_trim(inner) == 0) return
        n = 1
        do i = 1, len(inner)
            if (inner(i:i) == ',') n = n + 1
        end do
    end subroutine array_inner

    function parse_f64_token(tok) result(v)
        character(len = *), intent(in) :: tok
        character(len = :), allocatable :: t
        real(real64) :: v
        integer :: ios
        t = trim(adjustl(tok))
        if (t == 'null' .or. len(t) == 0) then
            v = nan64()
        else
            read(t, *, iostat = ios) v
            if (ios /= 0) v = nan64()
        end if
    end function parse_f64_token

    function parse_int_token(tok) result(v)
        character(len = *), intent(in) :: tok
        character(len = :), allocatable :: t
        integer :: v, ios
        t = trim(adjustl(tok))
        if (t == 'null' .or. len(t) == 0) then
            v = 0
        else
            read(t, *, iostat = ios) v
            if (ios /= 0) v = 0
        end if
    end function parse_int_token

    subroutine get_f64_array(buf, key, arr, n)
        character(len = *), intent(in) :: buf, key
        real(real64), allocatable, intent(out) :: arr(:)
        integer, intent(out) :: n
        character(len = :), allocatable :: inner
        logical :: ok
        integer :: i, start, idx
        call array_inner(buf, key, inner, n, ok)
        allocate(arr(n))
        if (n == 0) return
        start = 1
        idx = 0
        do i = 1, len(inner)
            if (inner(i:i) == ',') then
                idx = idx + 1
                arr(idx) = parse_f64_token(inner(start:i - 1))
                start = i + 1
            end if
        end do
        arr(n) = parse_f64_token(inner(start:len(inner)))
    end subroutine get_f64_array

    subroutine get_int_array(buf, key, arr, n)
        character(len = *), intent(in) :: buf, key
        integer, allocatable, intent(out) :: arr(:)
        integer, intent(out) :: n
        character(len = :), allocatable :: inner
        logical :: ok
        integer :: i, start, idx
        call array_inner(buf, key, inner, n, ok)
        allocate(arr(n))
        if (n == 0) return
        start = 1
        idx = 0
        do i = 1, len(inner)
            if (inner(i:i) == ',') then
                idx = idx + 1
                arr(idx) = parse_int_token(inner(start:i - 1))
                start = i + 1
            end if
        end do
        arr(n) = parse_int_token(inner(start:len(inner)))
    end subroutine get_int_array

    ! writing

    subroutine jb_init(b)
        type(jbuilder), intent(out) :: b
        allocate(character(len = 1024) :: b%s)
        b%n = 0
    end subroutine jb_init

    subroutine jb_ensure(b, extra)
        type(jbuilder), intent(inout) :: b
        integer, intent(in) :: extra
        integer :: cap, need
        character(len = :), allocatable :: tmp
        cap = len(b%s)
        need = b%n + extra
        if (need <= cap) return
        do while (cap < need)
            cap = cap * 2
        end do
        allocate(character(len = cap) :: tmp)
        tmp(1:b%n) = b%s(1:b%n)
        call move_alloc(tmp, b%s)
    end subroutine jb_ensure

    subroutine jb_push(b, str)
        type(jbuilder), intent(inout) :: b
        character(len = *), intent(in) :: str
        integer :: L
        L = len(str)
        if (L == 0) return
        call jb_ensure(b, L)
        b%s(b%n + 1:b%n + L) = str
        b%n = b%n + L
    end subroutine jb_push

    function jb_str(b) result(r)
        type(jbuilder), intent(in) :: b
        character(len = :), allocatable :: r
        r = b%s(1:b%n)
    end function jb_str

    ! Full-precision number
    function f64_to_str(x) result(r)
        real(real64), intent(in) :: x
        character(len = :), allocatable :: r
        character(len = 40) :: tmp
        if (.not. ieee_is_finite(x)) then
            r = 'null'
            return
        end if
        write(tmp, '(es24.16e3)') x
        r = trim(adjustl(tmp))
    end function f64_to_str

    subroutine jb_f64(b, x)
        type(jbuilder), intent(inout) :: b
        real(real64), intent(in) :: x
        call jb_push(b, f64_to_str(x))
    end subroutine jb_f64

    subroutine jb_int(b, k)
        type(jbuilder), intent(inout) :: b
        integer, intent(in) :: k
        character(len = 24) :: tmp
        write(tmp, '(i0)') k
        call jb_push(b, trim(adjustl(tmp)))
    end subroutine jb_int

    subroutine jb_f64_array(b, arr, n)
        type(jbuilder), intent(inout) :: b
        real(real64), intent(in) :: arr(:)
        integer, intent(in) :: n
        integer :: i
        call jb_push(b, '[')
        do i = 1, n
            if (i > 1) call jb_push(b, ',')
            call jb_f64(b, arr(i))
        end do
        call jb_push(b, ']')
    end subroutine jb_f64_array

    subroutine jb_int_array(b, arr, n)
        type(jbuilder), intent(inout) :: b
        integer, intent(in) :: arr(:)
        integer, intent(in) :: n
        integer :: i
        call jb_push(b, '[')
        do i = 1, n
            if (i > 1) call jb_push(b, ',')
            call jb_int(b, arr(i))
        end do
        call jb_push(b, ']')
    end subroutine jb_int_array

end module json_mod
