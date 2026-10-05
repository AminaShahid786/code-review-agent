def divide(a, b):
    return a / b

def average(numbers):
    total = 0
    for n in numbers:
        total = total + n
    return total / len(numbers)

def calc_discount(price, percent):
    x = price - (price * percent)
    return x