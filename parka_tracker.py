import os,json,re,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from threading import local
from datetime import datetime,timezone
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
_local=local()
def client():
    if not hasattr(_local,"session"):
        _local.session=requests.Session()
        _local.session.headers.update({"User-Agent":"ParkaPriceMonitor/1.1","Accept-Language":"en-US,en;q=0.9","Accept":"text/html,application/json;q=0.9,*/*;q=0.8"})
        _local.session.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=1, status_forcelist=[429,500,502,503,504], allowed_methods=["GET"], respect_retry_after_header=False)))
    return _local.session
def get(url):
    r=client().get(url,timeout=12)
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
# Public Shopify catalog adapter for eligible US storefronts.
SHOPIFY={"Mackage","Nobis","Outdoor Research"}
def shopify(brand,url):
    root=urlsplit(url)
    endpoint=f"{root.scheme}://{root.netloc}/products.json"
    for page in range(1,5):
        r=client().get(endpoint,params={"limit":250,"page":page},timeout=15)
        r.raise_for_status()
        catalog=r.json()["products"]
        if not catalog: break
        for p in catalog:
            name=p.get("title","")
            tags=str(p.get("tags",""))+" "+name+" "+p.get("product_type","")
            if not re.search(r"\b(?:men|mens|men's|male)\b",tags,re.I) or re.search(r"\b(?:women|womens|women's|girls|boys|kids)\b",tags,re.I): continue
            if "parka" not in name.lower(): continue
            link=f"{root.scheme}://{root.netloc}/products/{p['handle']}"
            page_soup=get(link)
            currencies={str(x.get("priceCurrency")) for x in structured(page_soup) if x.get("priceCurrency")}
            if currencies!={"USD"}: continue
            for v in p.get("variants",[]):
                if v.get("available") is not True: continue
                opts=[str(v.get("option"+str(i)) or "") for i in range(1,4)]
                sizes=[o for o in opts if o.lower() in ("m","l","medium","large")]
                if len(sizes)!=1: continue
                try:
                    price=float(v["price"])
                    regular=float(v.get("compare_at_price") or 0)
                except (ValueError,TypeError,KeyError): continue
                if price<=0: continue
                color=" / ".join(o for o in opts if o and o not in sizes) or "Unspecified"
                key="|".join([brand,link,str(v["id"]),sizes[0],color])
                yield key,dict(name=name,brand=brand,retailer=brand,size=sizes[0],color=color,price=price,url=link+"?variant="+str(v["id"]),regular=regular if regular>price else None)

def products(brand,url):
    soup=get(url)
    yield url,soup
    if any("Product" in ([p.get("@type")] if isinstance(p.get("@type"),str) else (p.get("@type") or [])) for p in structured(soup)): return
    links=set()
    for a in soup.select("a[href]"):
        u=urljoin(url,a["href"]).split("#")[0].split("?")[0]
        p=urlsplit(u)
        if p.netloc!=urlsplit(url).netloc: continue
        if not re.search(r"parka|down.coat|down.jacket|3q|langford|expedition|chateau|therme|ralle|nuuk",p.path,re.I): continue
        if p.path.rstrip("/").split("/")[-1].lower() in ("parkas","mens-parkas","parka"): continue
        links.add(u)
    for u in sorted(links)[:30]:
        try:
            time.sleep(1)
            yield u,get(u)
        except requests.RequestException as e: print(brand,u,str(e),flush=True)
def offers(brand,url,soup):
    for p in structured(soup):
        if "Product" not in ([p.get("@type")] if isinstance(p.get("@type"),str) else p.get("@type",[])): continue
        name=p.get("name","")
        if not isinstance(name,str) or not re.search(r"parka|down coat|3q",name,re.I) or re.search(r"women|girls|kids|boys",name,re.I): continue
        if not re.search(r"\b(?:men|mens|men\u2019s|men\x27s|male)\b",name+" "+url+" "+str(p.get("audience","")),re.I): continue
        brand_value=p.get("brand","")
        if isinstance(brand_value,dict): brand_value=brand_value.get("name","")
        actual=next((b for b in BRANDS if b.casefold()==str(brand_value).casefold() or re.search(r"\b"+re.escape(b)+r"\b",name,re.I)),None)
        if not actual and brand in DIRECT: actual=next((b for b in BRANDS if brand.startswith(b)),None)
        if not actual: continue
        size=p.get("size","")
        if isinstance(size,dict): size=size.get("name","")
        oo=p.get("offers",[])
        for o in oo if isinstance(oo,list) else [oo]:
            if not isinstance(o,dict) or str(o.get("availability","")).split("/")[-1]!="InStock" or o.get("priceCurrency")!="USD": continue
            variant_size=o.get("size") or size
            if isinstance(variant_size,dict): variant_size=variant_size.get("name","")
            if str(variant_size).strip().lower() not in ("m","l","medium","large"): continue
            try: price=float(o["price"])
            except (KeyError,ValueError,TypeError): continue
            if price<=0: continue
            color=str(p.get("color","Unspecified"))
            link=urljoin(url,o.get("url") or p.get("url") or url)
            key="|".join([brand,url,str(o.get("sku",p.get("sku",name))),str(variant_size),color])
            regular=None
            specs=o.get("priceSpecification",[])
            for spec in specs if isinstance(specs,list) else [specs]:
                if not isinstance(spec,dict): continue
                if str(spec.get("priceType","")).split("/")[-1] in ("ListPrice","StrikethroughPrice","RegularPrice","MSRP"):
                    try:
                        candidate=float(spec["price"])
                        if candidate>price and spec.get("priceCurrency","USD")=="USD": regular=max(regular or 0,candidate)
                    except (KeyError,ValueError,TypeError): pass
            yield key,dict(name=name,brand=actual,retailer=brand,size=str(variant_size),color=color,price=price,url=link,regular=regular)
def send(msg):
    r=requests.post(os.environ["PARKA_DISCORD_WEBHOOK"],json={"content":msg,"allowed_mentions":{"parse":[]}},timeout=20)
    if not r.ok: raise RuntimeError("Discord delivery failed: "+str(r.status_code))
def scan(entry):
    brand,url=entry
    items={}
    error=None
    if brand in SHOPIFY:
        try:
            items.update(shopify(brand,url))
        except Exception as e:
            error=f"{type(e).__name__}: {e}"
            print(brand,"catalog error",error,flush=True)
    try:
        for link,soup in products(brand,url):
            for key,item in offers(brand,link,soup): items[key]=item
        print(brand,len(items),"verified offers",flush=True)
    except Exception as e:
        error=f"{type(e).__name__}: {e}"
        print(brand,"source error",error,flush=True)
    return brand,items,error
def group_key(item):
    u=urlsplit(item["url"])
    return (item["retailer"],item["brand"],u.netloc,u.path.rstrip("/"),item["price"])

def notify_group(items, events):
    first=items[0]
    name=re.sub(r",\s*"+re.escape(first["color"])+r",\s*Size\s+[^,]+$","",first["name"],flags=re.I)
    colors={}
    for item in items:
        size={"medium":"M","large":"L","m":"M","l":"L"}.get(item["size"].lower(),item["size"])
        colors.setdefault(item["color"],set()).add(size)
    availability="; ".join(f"{color}: {', '.join(sorted(sizes))}" for color,sizes in sorted(colors.items()))
    refs=sorted({reference for _,reference in events})
    price=first["price"]
    title="Price drop" if any(kind=="Price drop" for kind,_ in events) else "Current sale"
    if len(refs)==1:
        pricing=f"${refs[0]:.2f} → ${price:.2f} ({100*(1-price/refs[0]):.0f}% off)"
    else:
        pricing=f"Now ${price:.2f}; qualifying previous/list prices ${refs[0]:.2f}–${refs[-1]:.2f}"
    msg=f"**{title} | {first['brand']} {name}**\n{first['retailer']} | {pricing}\nAvailable at this price: {availability}\n{first['url']}"
    if len(msg)>2000:
        msg=f"**{title} | {first['brand']} {name}**\n{pricing}\n{availability[:1200]}\n{first['url']}"
    send(msg)
    time.sleep(0.5)

def main():
    if not os.environ.get("PARKA_DISCORD_WEBHOOK"):
        raise RuntimeError("Missing PARKA_DISCORD_WEBHOOK")
    old=json.loads(STATE.read_text()) if STATE.exists() else {}
    count=0
    health={}
    groups={}
    events={}
    if os.environ.get("PARKA_TEST_NOTIFICATION")=="true":
        send("Parka tracker: Discord delivery test successful.")
    with ThreadPoolExecutor(max_workers=8) as pool:
        for source,items,error in pool.map(scan,SOURCES.items()):
            health[source]={"offers":len(items),"error":error,"status":"working" if items else ("error" if error else "no_verified_offers")}
            for key,item in items.items():
                count+=1
                prev=old.get(key,{}); price=item["price"]
                regular=item.get("regular")
                discount=100*(1-price/regular) if regular else 0
                drop=bool(prev and price<prev["price"])
                sale=discount>=20 and (not prev.get("sale_alerted") or drop)
                group=group_key(item)
                groups.setdefault(group,[]).append(item)
                if drop or sale:
                    title="Price drop" if drop else "Current sale"
                    reference=prev["price"] if drop else regular
                    events.setdefault(group,[]).append((title,reference))
                item["sale_alerted"]=bool(sale or (prev.get("sale_alerted") and discount>=20))
                old[key]=item
    for group,changes in events.items():
        notify_group(groups[group],changes)
    print(f"{len(events)} consolidated deal notifications",flush=True)
    working=sum(x["status"]=="working" for x in health.values())
    report={"checked_at":datetime.now(timezone.utc).isoformat(),"working":working,"total":len(health),"verified_variants":count,"unique_retailer_price_groups":len(groups),"notifications":len(events),"sources":health}
    STATE.parent.mkdir(exist_ok=True)
    Path("state/parka-health.json").write_text(json.dumps(report,indent=2))
    summary=os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary,"a") as f:
            f.write(f"## Parka coverage: {working}/{len(health)} sources returned verified offers\n\n")
            for source,h in health.items(): f.write(f"- {source}: {h['status']} ({h['offers']} offers)\n")
    if working<10: print(f"::warning::Low parka source coverage: {working}/{len(health)}")
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(old,indent=2,sort_keys=True))
if __name__=="__main__": main()
