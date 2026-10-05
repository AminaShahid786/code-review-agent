import os, sys

def load_data_file(file_path):
    try:
        f = open(file_path, 'r')
        data = f.read()
        f.close()
        return data
    except:
        return None

def compute_metrics(data_list):
    results = []
    for item in data_list:
        if item != None:
            results.append(item * 2)
    return results
