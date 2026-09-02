import openpyxl, re, json, datetime as dt
f="/root/.claude/uploads/fae20c10-d8ac-59cc-87ad-7eb93e78031d/2e894af2-______2026.08.28___.xlsx"
wb=openpyxl.load_workbook(f, data_only=True)
rows=[]
issues={"header_mismatch":[],"empty_sheet":[],"bad_date":0,"no_bottles":0,"no_hours":0,"neg_or_zero_hours":0,"blank_row":0}
for n in wb.sheetnames:
    ws=wb[n]
    vals=list(ws.iter_rows(values_only=True))
    if not vals or vals[0][0] is None:
        issues["empty_sheet"].append(n); continue
    hdr=[str(x) if x is not None else '' for x in vals[0]]
    if hdr[:5]!=['包裝日期','起始時間','結束時間','工時','瓶數']:
        issues["header_mismatch"].append((n,hdr))
    for i,r in enumerate(vals[1:],start=2):
        d,s,e,h,b = (list(r)+[None]*5)[:5]
        if d is None and b is None:
            issues["blank_row"]+=1; continue
        m=re.match(r'^\s*(\d{1,2})月(\d{1,2})日',str(d)) if d is not None else None
        if not m: issues["bad_date"]+=1
        if b in (None,0): issues["no_bottles"]+=1
        if h in (None,): issues["no_hours"]+=1
        elif isinstance(h,(int,float)) and h<=0: issues["neg_or_zero_hours"]+=1
        rows.append(dict(sheet=n,raw_date=str(d) if d is not None else None,
                         mo=int(m.group(1)) if m else None, day=int(m.group(2)) if m else None,
                         start=str(s) if s else None, end=str(e) if e else None,
                         hours=h if isinstance(h,(int,float)) else None,
                         bottles=b if isinstance(b,(int,float)) else None))
print("total data rows (non-blank):",len(rows))
print(json.dumps({k:(v if not isinstance(v,list) else v) for k,v in issues.items()},ensure_ascii=False,indent=1)[:2000])
json.dump(rows,open("rows.json","w"),ensure_ascii=False)
