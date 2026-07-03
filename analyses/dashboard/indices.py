"""Bundled index constituents for the batch/universe views.

US tickers are plain; European use Yahoo suffixes (.DE/.PA/.AS/.L/.MC/.SW).
S&P 500 is drawn from sp500.py. Regenerate via the fetch in build_static notes.
"""
from sp500 import SP500

_NASDAQ100 = [
    'AAPL', 'ABNB', 'ADBE', 'ADI', 'ADP', 'ADSK', 'AEP', 'ALAB', 'ALNY', 'AMAT', 'AMD', 'AMGN', 
    'AMZN', 'APP', 'ARM', 'ASML', 'AVGO', 'AXON', 'BKNG', 'BKR', 'CCEP', 'CDNS', 'CEG', 
    'CMCSA', 'COST', 'CPRT', 'CRWD', 'CRWV', 'CSCO', 'CSX', 'CTAS', 'DASH', 'DDOG', 'DXCM', 
    'EA', 'EXC', 'FANG', 'FAST', 'FER', 'FTNT', 'GEHC', 'GILD', 'GOOG', 'GOOGL', 'HON', 'IDXX', 
    'INTC', 'INTU', 'ISRG', 'KDP', 'KHC', 'KLAC', 'LIN', 'LITE', 'LRCX', 'MAR', 'MCHP', 'MDLZ', 
    'MELI', 'META', 'MNST', 'MPWR', 'MRVL', 'MSFT', 'MSTR', 'MU', 'NBIS', 'NFLX', 'NVDA', 
    'NXPI', 'ODFL', 'ORLY', 'PANW', 'PAYX', 'PCAR', 'PDD', 'PEP', 'PLTR', 'PYPL', 'QCOM', 
    'REGN', 'RKLB', 'ROP', 'ROST', 'SBUX', 'SHOP', 'SNDK', 'SNPS', 'STX', 'TER', 'TMUS', 'TRI', 
    'TSLA', 'TTWO', 'TXN', 'VRTX', 'WBD', 'WDAY', 'WDC', 'WMT', 'XEL',
]
_DJIA = [
    'AAPL', 'AMGN', 'AMZN', 'AXP', 'BA', 'CAT', 'CRM', 'CSCO', 'CVX', 'DIS', 'GS', 'HD', 'HON', 
    'IBM', 'JNJ', 'JPM', 'KO', 'MCD', 'MMM', 'MRK', 'MSFT', 'NKE', 'NVDA', 'PG', 'SHW', 'TRV', 
    'UNH', 'V', 'VZ', 'WMT',
]
_DAX = [
    'ADS.DE', 'AIR.PA', 'ALV.DE', 'BAS.DE', 'BAYN.DE', 'BEI.DE', 'BMW.DE', 'BNR.DE', 'CBK.DE', 
    'CON.DE', 'DB1.DE', 'DBK.DE', 'DHL.DE', 'DTE.DE', 'DTG.DE', 'ENR.DE', 'EOAN.DE', 'FME.DE', 
    'FRE.DE', 'G1A.DE', 'G24.DE', 'HEI.DE', 'HEN3.DE', 'HNR1.DE', 'IFX.DE', 'MBG.DE', 'MRK.DE', 
    'MTX.DE', 'MUV2.DE', 'PAH3.DE', 'QIA.DE', 'RHM.DE', 'RWE.DE', 'SAP.DE', 'SHL.DE', 'SIE.DE', 
    'SY1.DE', 'VNA.DE', 'VOW3.DE', 'ZAL.DE',
]
_STOXX50 = [
    'ABI.BR', 'AD.AS', 'ADS.DE', 'ADYEN.AS', 'AI.PA', 'AIR.PA', 'ALV.DE', 'ARGX.BR', 'ASML.AS', 
    'BAS.DE', 'BAYN.DE', 'BBVA.MC', 'BMW.DE', 'BN.PA', 'BNP.PA', 'CS.PA', 'DB1.DE', 'DBK.DE', 
    'DG.PA', 'DHL.DE', 'DTE.DE', 'EL.PA', 'ENEL.MI', 'ENI.MI', 'ENR.DE', 'IBE.MC', 'IFX.DE', 
    'INGA.AS', 'ISP.MI', 'ITX.MC', 'MBG.DE', 'MC.PA', 'MUV2.DE', 'NDA-FI.HE', 'OR.PA', 
    'PRX.AS', 'RACE.MI', 'RHM.DE', 'RMS.PA', 'SAF.PA', 'SAN.MC', 'SAN.PA', 'SAP.DE', 'SGO.PA', 
    'SIE.DE', 'SU.PA', 'TTE.PA', 'UCG.MI', 'VOW.DE', 'WKL.AS',
]
_FTSE100 = [
    'AAF.L', 'AAL.L', 'ABDN.L', 'ABF.L', 'ADM.L', 'ALW.L', 'ANTO.L', 'AUTO.L', 'AV.L', 'AZN.L', 
    'BA.L', 'BAB.L', 'BARC.L', 'BATS.L', 'BBOX.L', 'BEZ.L', 'BGEO.L', 'BLND.L', 'BNZL.L', 
    'BP.L', 'BRBY.L', 'BT-A.L', 'BTRW.L', 'CCC.L', 'CCEP.L', 'CCH.L', 'CNA.L', 'CPG.L', 
    'CRDA.L', 'CTEC.L', 'DCC.L', 'DGE.L', 'DPLM.L', 'EDV.L', 'ENT.L', 'EXPN.L', 'FCIT.L', 
    'FRES.L', 'GAW.L', 'GLEN.L', 'GSK.L', 'HLMA.L', 'HLN.L', 'HSBA.L', 'HSX.L', 'HWDN.L', 
    'IAG.L', 'ICG.L', 'IGG.L', 'IHG.L', 'III.L', 'IMB.L', 'IMI.L', 'INF.L', 'INVP.L', 'ITRK.L', 
    'JD.L', 'KGF.L', 'LAND.L', 'LGEN.L', 'LLOY.L', 'LMP.L', 'LSEG.L', 'MKS.L', 'MNG.L', 
    'MRO.L', 'MTLN.L', 'NG.L', 'NWG.L', 'NXT.L', 'PCT.L', 'PRU.L', 'PSH.L', 'PSN.L', 'PSON.L', 
    'REL.L', 'RIO.L', 'RKT.L', 'RR.L', 'RTO.L', 'SBRY.L', 'SDLF.L', 'SDR.L', 'SGE.L', 'SGRO.L', 
    'SHEL.L', 'SMIN.L', 'SMT.L', 'SN.L', 'SPX.L', 'SSE.L', 'STAN.L', 'STJ.L', 'SVT.L', 
    'TSCO.L', 'ULVR.L', 'UU.L', 'VOD.L', 'WEIR.L', 'WTB.L',
]

INDICES = {
    "sp500": sorted(SP500),
    "nasdaq100": _NASDAQ100,
    "djia": _DJIA,
    "stoxx50": _STOXX50,
    "ftse100": _FTSE100,
    "dax": _DAX,
}

# display order + labels for the UI
INDEX_LABELS = [
    ("djia", "DJIA"),
    ("sp500", "S&P 500"),
    ("nasdaq100", "NASDAQ 100"),
    ("stoxx50", "STOXX 50"),
    ("ftse100", "FTSE 100"),
    ("dax", "DAX"),
]
