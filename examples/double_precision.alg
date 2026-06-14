var num low1
var num high1
var num low2
var num high2
var num low_res
var num high_res
var num carry
set high1 = 1
set low1 = 0 - 1
set high2 = 2
set low2 = 2

set low_res = low1 + low2
set carry = 0
if low1 < 0:
  if low2 < 0:
    set carry = 1
  else:
    if low_res >= 0:
      set carry = 1
    end
  end
else:
  if low2 < 0:
    if low_res >= 0:
      set carry = 1
    end
  end
end
set high_res = high1 + high2 + carry

print(high_res)
print(low_res)
