import csv
from collections import defaultdict

data = defaultdict(lambda: {'trades': 0, 'win': 0, 'total_pnl': 0.0})

with open('phase4_ex2022_raw.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['type'] != 'EXIT':
            continue
        sym = row['symbol']
        strat = row['strategy']
        year = row['date'][:4]
        pnl = float(row['pnl_pct'])
        key = (sym, strat, year)
        data[key]['trades'] += 1
        data[key]['total_pnl'] += pnl
        if pnl > 0:
            data[key]['win'] += 1

def print_table(title, sym, strat):
    print(f'\n=== {title} ===')
    print(f"{'Year':<8} {'Trades':>6} {'Wins':>6} {'Win%':>8} {'CumPnL%':>10}")
    years = sorted(set(k[2] for k in data if k[0]==sym and k[1]==strat))
    total_t = 0
    total_w = 0
    total_pnl = 0.0
    for year in years:
        d = data[(sym, strat, year)]
        wr = d['win']/d['trades']*100 if d['trades']>0 else 0
        print(f"{year:<8} {d['trades']:>6} {d['win']:>6} {wr:>7.1f}% {d['total_pnl']:>+9.2f}%")
        total_t += d['trades']
        total_w += d['win']
        total_pnl += d['total_pnl']
    wr_all = total_w/total_t*100 if total_t>0 else 0
    print(f"{'TOTAL':<8} {total_t:>6} {total_w:>6} {wr_all:>7.1f}% {total_pnl:>+9.2f}%")

print_table("QQQ COUNTERPUNCH (反击)", "QQQ", "COUNTERPUNCH")
print_table("QQQ SPEARHEAD (进攻)", "QQQ", "SPEARHEAD")
print_table("IVV COUNTERPUNCH (反击)", "IVV", "COUNTERPUNCH")
print_table("IVV SPEARHEAD (进攻)", "IVV", "SPEARHEAD")
