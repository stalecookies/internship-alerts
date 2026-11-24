import os,json,re,time
from concurrent.futures import ThreadPoolExecutor
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
SOURCES.update({
  "Moose Knuckles": "https://www.mooseknucklescanada.com/us-en/men/outerwear/parkas",
  "Moncler": "https://www.moncler.com/en-us/men/outerwear/long-down-jackets",
  "Mackage": "https://www.mackage.com/collections/mens-parkas",
  "Woolrich": "https://www.woolrich.com/us/en/men/outerwear/parkas",
  "Nobis": "https://nobis.com/collections/mens-parkas",
  "Parajumpers": "https://www.parajumpers.it/us/en/men/outerwear/",
  "Rab": "https://rab.equipment/us/mens/down-jackets",
  "Norrøna": "https://www.norrona.com/en-GB/products/men/",
  "Outdoor Research": "https://www.outdoorresearch.com/collections/mens-jackets",
  "Mountain Hardwear": "https://www.mountainhardwear.com/c/mens-insulated-jackets/",
  "Marmot": "https://www.marmot.com/men/jackets-and-vests/",
  "REI": "https://www.rei.com/search?q=mens+parka",
  "Backcountry": "https://www.backcountry.com/search?q=mens%20parka",
  "evo": "https://www.evo.com/shop/clothing/jackets/parkas/mens",
  "CampSaver": "https://www.campsaver.com/s/mens-parka",
  "Public Lands": "https://www.publiclands.com/search/SearchDisplay?searchTerm=mens%20parka",
  "Nordstrom": "https://www.nordstrom.com/sr?keyword=mens%20parka",
  "Bloomingdale's": "https://www.bloomingdales.com/shop/search?keyword=mens%20parka",
  "Saks": "https://www.saksfifthavenue.com/search?q=mens%20parka",
  "Neiman Marcus": "https://www.neimanmarcus.com/search.jsp?Ntt=mens%20parka",
  "SSENSE": "https://www.ssense.com/en-us/men/parkas",
  "MR PORTER": "https://www.mrporter.com/en-us/mens/clothing/coats-and-jackets/parkas",
  "Farfetch": "https://www.farfetch.com/shopping/men/parkas-2/items.aspx",
  "END.": "https://www.endclothing.com/us/catalogsearch/result?q=parka",
  "Mytheresa": "https://www.mytheresa.com/us/en/men/clothing/jackets/parkas",
  "Nordstrom Rack": "https://www.nordstromrack.com/sr?keyword=mens%20parka",
  "Saks OFF 5TH": "https://www.saksoff5th.com/search?q=mens%20parka",
  "Sierra": "https://www.sierra.com/s~mens-parka/",
  "Arc'teryx Outlet": "https://outlet.arcteryx.com/us/en/c/mens/insulated-jackets",
  "Patagonia Web Specials": "https://www.patagonia.com/shop/web-specials/mens/jackets-vests",
  "ShopStyle": "https://www.shopstyle.com/browse/mens-coats?fts=parka",
  "Lyst": "https://www.lyst.com/shop/mens-parkas/",
  "Google Shopping": "https://www.google.com/search?tbm=shop&q=mens+premium+down+parka",
  "Arc'teryx Ralle Down": "https://arcteryx.com/us/en/shop/mens/ralle-down-parka",
  "Canada Goose parkas": "https://www.canadagoose.com/us/en/mens-parkas/"
})
DIRECT=set(list(SOURCES)[:16]) | {"Arc'teryx Outlet","Patagonia Web Specials","Arc'teryx Ralle Down","Canada Goose parkas"}
BRANDS=["Canada Goose","Moose Knuckles","Moncler","Mackage","Woolrich","Nobis","Parajumpers","Arc'teryx","Arcteryx","Patagonia","Fjallraven","Fjällräven","Norrøna","Norrona","Rab","The North Face","Outdoor Research","Mountain Hardwear","Marmot"]
STATE=Path("state/parka-prices.json")
session=requests.Session()
session.headers["User-Agent"]="ParkaPriceMonitor/1.0"
def get(url):
    r=session.get(url,timeout=12)
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
        if p.path.rstrip("/").split("/")[-1].lower() in ("parkas","mens-parkas","parka"): continue
        links.add(u)
    for u in sorted(links)[:12]:
        try:
            time.sleep(1)
            yield u,get(u)
        except requests.RequestException as e: print(brand,type(e).__name__)
def offers(brand,url,soup):
    for p in structured(soup):
        if "Product" not in ([p.get("@type")] if isinstance(p.get("@type"),str) else p.get("@type",[])): continue
        name=p.get("name","")
        if not isinstance(name,str) or "parka" not in name.lower() or re.search(r"women|girls|kids|boys",name,re.I): continue
        brand_value=p.get("brand","")
        if isinstance(brand_value,dict): brand_value=brand_value.get("name","")
        actual=next((b for b in BRANDS if b.casefold()==str(brand_value).casefold() or re.search(r"\b"+re.escape(b)+r"\b",name,re.I)),None)
        if not actual and brand in DIRECT: actual=next((b for b in BRANDS if brand.startswith(b)),None)
        if not actual: continue
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
            regular=None
            specs=o.get("priceSpecification",[])
            for spec in specs if isinstance(specs,list) else [specs]:
                if not isinstance(spec,dict): continue
                if str(spec.get("priceType","")).split("/")[-1] in ("ListPrice","StrikethroughPrice","RegularPrice","MSRP"):
                    try:
                        candidate=float(spec["price"])
                        if candidate>price and spec.get("priceCurrency","USD")=="USD": regular=max(regular or 0,candidate)
                    except (KeyError,ValueError,TypeError): pass
            yield key,dict(name=name,brand=actual,retailer=brand,size=str(size),color=color,price=price,url=link,regular=regular)
def send(msg):
    r=requests.post(os.environ["PARKA_DISCORD_WEBHOOK"],json={"content":msg,"allowed_mentions":{"parse":[]}},timeout=20)
    if not r.ok: raise RuntimeError("Discord delivery failed: "+str(r.status_code))
def scan(entry):
    brand,url=entry
    items={}
    try:
        for link,soup in products(brand,url):
            for key,item in offers(brand,link,soup): items[key]=item
        print(brand,len(items),"verified offers",flush=True)
    except Exception as e:
        print(brand,"source error",type(e).__name__,flush=True)
    return items
def main():
    if not os.environ.get("PARKA_DISCORD_WEBHOOK"):
        raise RuntimeError("Missing PARKA_DISCORD_WEBHOOK")
    old=json.loads(STATE.read_text()) if STATE.exists() else {}
    count=0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for items in pool.map(scan,SOURCES.items()):
            for key,item in items.items():
                count+=1
                prev=old.get(key,{}); price=item["price"]
                regular=item.get("regular")
                discount=100*(1-price/regular) if regular else 0
                drop=bool(prev and price<prev["price"])
                sale=discount>=20 and (not prev.get("sale_alerted") or drop)
                if drop or sale:
                    title="Price drop" if drop else "Current sale"
                    reference=prev["price"] if drop else regular
                    pct=100*(1-price/reference)
                    send(f'**{title} | {item["brand"]} {item["name"]}**\n{item["retailer"]} | ${reference:.2f} → ${price:.2f} ({pct:.0f}% off) | Size {item["size"]} | {item["color"]}\n{item["url"]}')
                    time.sleep(0.5)
                item["sale_alerted"]=bool(sale or (prev.get("sale_alerted") and discount>=20))
                old[key]=item
    if not count: raise RuntimeError("No size-verified offers extracted; source adapters need validation")
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(old,indent=2,sort_keys=True))
if __name__=="__main__": main()
