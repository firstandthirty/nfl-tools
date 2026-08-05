import pandas as pd
from pathlib import Path
p = Path('data/raw/projections/pff/2026/week_01/snapshots/08_04_26_1100projections.csv')
df = pd.read_csv(p)
print('shape', df.shape)
print('columns', df.columns.tolist())
print('positions', df['position'].value_counts(dropna=False).to_dict())
print('teams', df['teamName'].value_counts(dropna=False).head(20).to_dict())
print('missing', df.isna().sum().to_dict())
print('dup_rows', int(df.duplicated(subset=['playerName','teamName','position']).sum()))
print('players', df[['playerName','teamName','position']].head(20).to_string(index=False))
