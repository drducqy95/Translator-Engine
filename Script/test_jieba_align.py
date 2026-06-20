import jieba.posseg as pseg

text = "电子机械的声音"
words = list(pseg.cut(text))
for w, f in words:
    print(w, f)
