# -*- coding: utf-8 -*-
import glob
import sys

import pandas as pd

for f in sorted(glob.glob(sys.argv[1] if len(sys.argv) > 1 else 'uploads/client_excel/*.xlsx')):
    xl = pd.ExcelFile(f)
    print(f, '->', xl.sheet_names)
