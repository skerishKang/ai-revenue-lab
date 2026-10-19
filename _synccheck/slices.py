import datetime as dt
start = 1791834544000
end = 1791837624000
iso = lambda ms: dt.datetime.fromtimestamp(ms/1000, tz=dt.timezone(dt.timedelta(hours=9))).isoformat(timespec='seconds')
print(f"WINDOW_KST {iso(start)} .. {iso(end)}  span_ms={end-start}")
cur = start
i = 0
while cur < end:
    nxt = min(cur + 300000, end)
    i += 1
    print(f"{i}\t{iso(cur)}\t{iso(nxt)}\t{cur}\t{nxt}\t{nxt-cur}")
    cur = nxt
print("TOTAL_SLICES", i)
