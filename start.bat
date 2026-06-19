@echo off
echo در حال نصب کتابخانه‌ها...
pip install -r requirements.txt
echo.
echo سرور در حال راه‌اندازی...
echo آدرس رو از گوشیت باز کن: http://[IP کامپیوتر]:5000
echo.
python app.py
pause
