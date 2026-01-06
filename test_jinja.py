
try:
    val = 1234.56
    s = "{:,.0f}".format(val).replace(",", ".")
    print(f"Float {val}: {s}")
    
    val = 0.0
    s = "{:,.0f}".format(val).replace(",", ".")
    print(f"Float {val}: {s}")
    
    val = 0
    s = "{:,.0f}".format(val).replace(",", ".")
    print(f"Int {val}: {s}")
    
    # What if None? Template logic in main.py ensures it's not None (0.0 default)
    # But let's check just in case it slips through
    try:
        val = None
        s = "{:,.0f}".format(val).replace(",", ".")
        print(f"None: {s}")
    except Exception as e:
        print(f"None failed: {e}")
        
except Exception as e:
    print(f"Global fail: {e}")
