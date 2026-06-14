var num max_pal
var num limit
var num i
var num j
var num prod
var num temp
var num rev
var num rem

set max_pal = 0
input(limit)
set i = limit - 1

while i >= 100:
    set j = i
    while j >= 100:
        set prod = i * j
        if prod <= max_pal:
            set j = 0
        else:
            set temp = prod
            set rev = 0
            while temp > 0:
                set rem = temp % 10
                set rev = rev * 10
                set rev = rev + rem
                set temp = temp // 10
            end
            if rev == prod:
                set max_pal = prod
            end
        end
        set j = j - 1
    end
    set i = i - 1
end

print(max_pal)
