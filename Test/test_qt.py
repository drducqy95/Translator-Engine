import sys
sys.path.append("/sdcard/My Agent/Translator Engine/Script")
from qt_engine import QTEngine
qt = QTEngine()
print("Draft 1:", qt.translate("系统很抽象，还好我也是")[0])
print("Draft 2:", qt.translate("大奉打更人")[0])
print("Draft 3:", qt.translate("火影：人在木叶，我叫漩涡面麻")[0])
qt.close()
