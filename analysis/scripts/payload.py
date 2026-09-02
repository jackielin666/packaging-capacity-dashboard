import json, statistics as st
from collections import defaultdict
clean=json.load(open("clean.json"))
ok=[r for r in clean if r["valid"]]
by=defaultdict(list)
for r in ok: by[r["sheet"]].append(r)
P=[]
alldays=defaultdict(set)
for r in clean: alldays[r["sheet"]].add(r["date"])
for s,v in by.items():
    rates=[r["bottles"]/r["hours"] for r in v]
    B=sum(r["bottles"] for r in v); H=sum(r["hours"] for r in v)
    p75=st.quantiles(rates,n=4)[2] if len(rates)>3 else max(rates)
    P.append(dict(sku=s,b=B,h=round(H,1),d=len(alldays[s]),n=len(v),
        rate=round(B/H,0),med=round(st.median(rates),0),p75=round(p75,0),best=round(max(rates),0),
        cv=round(100*st.pstdev(rates)/st.mean(rates),0), save=round(max(H-B/p75,0),1)))
TB=sum(p["b"] for p in P); TH=sum(p["h"] for p in P)
print("total save all SKU:",round(sum(p["save"] for p in P),0),"hrs =",round(100*sum(p["save"] for p in P)/TH,1),"%")
topB=sorted(P,key=lambda x:-x["b"])[:10]
topD=sorted(P,key=lambda x:-x["d"])[:10]
mon=defaultdict(lambda:[0,0.0])
for r in ok: mon[r["date"][:7]][0]+=r["bottles"]; mon[r["date"][:7]][1]+=r["hours"]
months=[dict(m=k,b=v[0],h=round(v[1],1),rate=round(v[0]/v[1],0)) for k,v in sorted(mon.items())]
focus=sorted({p["sku"] for p in topB}|{p["sku"] for p in topD})
gap=[p for p in P if p["sku"] in focus]
gap.sort(key=lambda x:-x["save"])
out=dict(period=["2025-10-01","2026-08-26"],skus=len(P),recs=len(clean),days=len(set(r["date"] for r in clean)),
    bottles=TB,hours=round(TH,1),rate=round(TB/TH,0),topB=topB,topD=topD,gap=gap,months=months,
    save=round(sum(p["save"] for p in P),0))
json.dump(out,open("payload.json","w"),ensure_ascii=False)
print(json.dumps(out,ensure_ascii=False)[:400])
print("focus n=",len(focus))
