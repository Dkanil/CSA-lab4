var num count
var num i
var num j
var num limit
var num t
var num a[32]

input(count)
if count > 32:
    set count = 32
end

set i = 0
while i < count:
    input(a[i])
    set i = i + 1
end

set i = 0
while i < count:
    set limit = count - i
    set limit = limit - 1
    set j = 0
    while j < limit:
        if a[j] > a[j + 1]:
            set t = a[j]
            set a[j] = a[j + 1]
            set a[j + 1] = t
        end
        set j = j + 1
    end
    set i = i + 1
end

set i = 0
while i < count:
    print(a[i])
    set i = i + 1
end
