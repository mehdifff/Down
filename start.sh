#!/bin/bash
echo "در حال نصب کتابخانه‌ها..."
pip3 install -r requirements.txt
echo ""
echo "سرور در حال راه‌اندازی..."
echo "آدرس رو از گوشیت باز کن: http://$(ipconfig getifaddr en0 2>/dev/null || hostname -I | awk '{print $1}'):5000"
echo ""
python3 app.py
