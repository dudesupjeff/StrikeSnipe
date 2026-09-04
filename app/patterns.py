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
