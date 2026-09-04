# Kind of niche and risky to be buying these listings for a low ROI since they can varry greatly in price and often aren't worth the risk, time, and effort to be selling them
# Most of the listings you get from this are from the amber or acid fade groups...not really worth buying

def describe(item):
    notes=[]
    if item.get('phase'):
        notes.append(f"Doppler phase: {item['phase']}")
    if item.get('fade'):
        pct=(item.get('fade') or {}).get('percentage')
        if pct is not None: notes.append(f"Fade: {pct}%")
    if item.get('blue_gem'):
        notes.append('Blue-gem metadata present')
    return notes
