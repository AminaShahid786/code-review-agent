def find_duplicates(lst):
    result = []
    for i in range(len(lst)):
        for j in range(len(lst)):
            if i != j and lst[i] == lst[j] and lst[i] not in result:
                result.append(lst[i])
    return result

def process_data(data):
    output = []
    for item in data:
        if item != None:
            if item > 0:
                output.append(item * 2)
    return output