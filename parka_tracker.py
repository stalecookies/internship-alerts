import os,json,re,time
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import requests
from bs4 import BeautifulSoup
SOURCES={
"Patagonia":"https://www.patagonia.com/shop/mens/jackets-vests/parkas-coats",
"The North Face":"https://www.thenorthface.com/en-us/c/mens/mens-jackets-and-vests/mens-parkas-300775",
"Fjallraven":"https://www.fjallraven.com/us/en-us/men/jackets/parkas/",
"Arc'teryx":"https://arcteryx.com/us/en/shop/mens/therme-down-parka-9914",
"Canada Goose":"https://www.canadagoose.com/en-us/products/langford-parka-2052m",
}
STATE=Path("state/parka-prices.json")
session=requests.Session()
session.headers["User-Agent"]="ParkaPriceMonitor/1.0"
def get(url):
    r=session.get(url,timeout=25)
    r.raise_for_status()
    return BeautifulSoup(r.text,"html.parser")
def nodes(x):
    if isinstance(x,dict):
        yield x
        for v in x.values(): yield from nodes(v)
    elif isinstance(x,list):
        for v in x: yield from nodes(v)
def structured(soup):
    for tag in soup.select('script[type="application/ld+json"]'):
        try: yield from nodes(json.loads(tag.get_text()))
        except (ValueError,TypeError): continue
def products(brand,url):
    soup=get(url)
    yield url,soup
    if "/products/" in url or "/shop/mens/therme" in url: return
    links=set()
    for a in soup.select("a[href]"):
        u=urljoin(url,a["href"]).split("#")[0].split("?")[0]
        p=urlsplit(u)
        if p.netloc!=urlsplit(url).netloc or "parka" not in p.path.lower(): continue
        if not ("/product/" in p.path or "/en-us/p/" in p.path or "/jackets/parkas/" in p.path and p.path.rstrip("/").split("/")[-1]!="parkas"): continue
        links.add(u)
    for u in sorted(links)[:35]:
        try:
            time.sleep(1)
            yield u,get(u)
        except requests.RequestException as e: print(brand,type(e).__name__)
def offers(brand,url,soup):
    for p in structured(soup):
        if "Product" not in ([p.get("@type")] if isinstance(p.get("@type"),str) else p.get("@type",[])): continue
        name=p.get("name","")
        if not isinstance(name,str) or "parka" not in name.lower() or re.search(r"women|girls|kids|boys",name,re.I): continue
        size=p.get("size","")
        if isinstance(size,dict): size=size.get("name","")
        if str(size).strip().lower() not in ("m","l","medium","large"): continue
        oo=p.get("offers",[])
        for o in oo if isinstance(oo,list) else [oo]:
            if not isinstance(o,dict) or str(o.get("availability","")).split("/")[-1]!="InStock" or o.get("priceCurrency")!="USD": continue
            try: price=float(o["price"])
            except (KeyError,ValueError,TypeError): continue
            if price<=0: continue
            color=str(p.get("color","Unspecified"))
            link=urljoin(url,o.get("url") or p.get("url") or url)
            key="|".join([brand,url,str(p.get("sku",name)),str(size),color])
            yield key,dict(name=name,brand=brand,size=str(size),color=color,price=price,url=link)
def send(msg):
    r=requests.post(os.environ["PARKA_DISCORD_WEBHOOK"],json={"content":msg,"allowed_mentions":{"parse":[]}},timeout=20)
    if not r.ok: raise RuntimeError("Discord delivery failed: "+str(r.status_code))
def main():
    old=json.loads(STATE.read_text()) if STATE.exists() else {}
    count=0
    for brand,url in SOURCES.items():
        found=0
        try:
            for link,soup in products(brand,url):
                for key,item in offers(brand,link,soup):
                    found+=1
                    prev=old.get(key,{}); price=item["price"]
                    if prev and price<prev["price"]:
                        send(f'**Price drop | {brand} {item["name"]}**\n${prev["price"]:.2f} → ${price:.2f} | Size {item["size"]} | {item["color"]}\n{item["url"]}')
                    old[key]=item
            print(brand,found,"verified offers")
            count+=found
        except requests.RequestException as e: print(brand,type(e).__name__)
    if not count: raise RuntimeError("No size-verified offers extracted; source adapters need validation")
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(old,indent=2,sort_keys=True))
if __name__=="__main__": main()
