# -*- coding: utf-8 -*-
"""Verify OCR: engine + parse + HTTP API."""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont


def make_receipt_image():
    img = Image.new("RGB", (400, 280), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("msyh.ttc", 18)
    except OSError:
        font = ImageFont.load_default()
    lines = [
        "微信支付",
        "商户：测试餐饮店",
        "2025-05-20",
        "¥128.50",
        "交易成功",
    ]
    y = 30
    for ln in lines:
        d.text((20, y), ln, fill="black", font=font)
        y += 40
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def main():
    from app import app, parse_ocr_text

    sample = (
        "微信支付\n商户：测试餐饮店\n2025-05-20\n¥128.50\n交易成功"
    )
    rows = parse_ocr_text(sample)
    assert rows, "parse_ocr_text should find at least one record"
    assert abs(rows[0]["amount"] - 128.5) < 0.01, rows[0]
    assert rows[0]["date"].startswith("2025-05-20"), rows[0]
    print("parse_ocr_text OK amount=", rows[0]["amount"], "date=", rows[0]["date"])

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "admin"

    buf = make_receipt_image()
    r = client.post(
        "/api/ocr/recognize",
        data={"image": (buf, "test.png")},
        content_type="multipart/form-data",
    )
    print("API status:", r.status_code)
    data = r.get_json()
    print("API response keys:", list(data.keys()) if data else None)
    if not data or not data.get("success"):
        print("FAIL:", data)
        sys.exit(1)
    print("API OK, transactions:", len(data.get("transactions", [])))
    if data.get("transactions"):
        print(" first:", data["transactions"][0])


if __name__ == "__main__":
    main()
