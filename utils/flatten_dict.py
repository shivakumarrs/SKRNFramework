car = {
"brand": "Toyota",
"model": "Innova",
"engine": {
   "type": "Diesel",
   "cc": 2400
},
"colors": ["white", "black"]
}

def flatten(inp, child_key = None):
  outp = dict()
  for key, value in inp.items():
    if type(value) == dict:
      child_dict = flatten(value, key)
      outp.update(child_dict)
    elif type(value) == list:
      for i in range(0, len(value)):
        if type(value[i]) == dict:
          child_dict = flatten(value[i], str(key)+"."+str(i))
          outp.update(child_dict)
        else:
          outp[str(key)+"."+str(i)] = value[i]
    else:
      if child_key != None:
        outp[child_key+"."+key] = value
      else:
        outp[key] = value
  return outp
  
 
print(flatten(car))
 
# Output:
# {
# "brand": "Toyota",
# "model": "Innova",
# "engine.type": "Diesel",
# "engine.cc": 2400,
# "colors.0": "white",
# "colors.1": "black"
# }