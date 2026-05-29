#!/usr/bin/env python3
import sys

print("=== 检查OCR库安装情况 ===")

libs = [
    ('rapidocr_onnxruntime', 'RapidOCR'),
    ('paddleocr', 'PaddleOCR'),
    ('easyocr', 'EasyOCR'),
    ('pytesseract', 'Tesseract'),
]

for lib, name in libs:
    try:
        __import__(lib)
        print(f"✅ {name} ({lib}): 已安装")
    except ImportError as e:
        print(f"❌ {name} ({lib}): 未安装 - {e}")

print("\n=== 测试OCR识别 ===")
try:
    from rapidocr_onnxruntime import RapidOCR
    print("RapidOCR 可以导入")
    engine = RapidOCR()
    print("RapidOCR 引擎创建成功")
except Exception as e:
    print(f"RapidOCR 错误: {e}")
