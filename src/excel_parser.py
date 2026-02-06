"""
Excel Parser Module

Reads FactSet Excel files and extracts portfolio data.
- Tab: ContributionMasterRisk
- Header row: 7
- Data starts: row 10
- Period string: row 6
- End marker: first blank Ticker cell
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import openpyxl


@dataclass
class SecurityRow:
    """Represents a single security row from the Excel file."""
    ticker: str
    security_name: str
    port_ending_weight: float
    contribution_to_return: float
    gics: str
    
    def is_cash_or_fee(self) -> bool:
        """Check if this row is cash or fees (GICS == 'NA')."""
        return self.gics == "NA" or self.gics is None


@dataclass
class PortfolioData:
    """Parsed data from a single portfolio Excel file."""
    portcode: str
    period: str
    securities: list[SecurityRow]
    source_file: Path
    
    def get_filtered_securities(self) -> list[SecurityRow]:
        """Return securities excluding cash/fees rows."""
        return [s for s in self.securities if not s.is_cash_or_fee()]


def extract_portcode_from_filename(filename: str) -> str:
    """
    Extract PORTCODE from filename.
    Pattern: PORTCODE_*_MMDDYYYY.xlsx
    PORTCODE = everything before the first underscore
    """
    base_name = Path(filename).stem  # Remove .xlsx
    parts = base_name.split('_')
    if parts:
        return parts[0]
    return base_name


def parse_excel_file(file_path: Path) -> PortfolioData:
    """
    Parse a FactSet Excel file and extract portfolio data.
    
    Args:
        file_path: Path to the Excel file
        
    Returns:
        PortfolioData object with extracted information
        
    Raises:
        ValueError: If the file format is invalid or required data is missing
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)
    
    # Check for required sheet
    sheet_name = "ContributionMasterRisk"
    if sheet_name not in wb.sheetnames:
        raise ValueError(f"Required sheet '{sheet_name}' not found in {file_path}")
    
    ws = wb[sheet_name]
    
    # Extract period from row 6
    period_value = ws.cell(row=6, column=1).value
    if not period_value:
        raise ValueError(f"Period not found in row 6 of {file_path}")
    period = str(period_value).strip()
    
    # Find column indices by scanning row 7 for headers
    # Security Name header may be blank, but it's always left of Ticker
    col_map = {}
    ticker_col = None
    
    for col in range(1, ws.max_column + 1):
        header = ws.cell(row=7, column=col).value
        if header is None:
            continue
        header_str = str(header).strip()
        if not header_str:
            continue
        header_key = header_str.lower()
        if header_key == "ticker":
            col_map["Ticker"] = col
            ticker_col = col
        elif header_key == "security name":
            col_map["Security Name"] = col
        elif header_key == "port. ending weight":
            col_map["Port. Ending Weight"] = col
        elif header_key == "contribution to return":
            col_map["Contribution To Return"] = col
        elif header_key == "gics":
            col_map["GICS"] = col
    
    # Validate required columns found
    required_cols = ["Ticker", "Port. Ending Weight", "Contribution To Return", "GICS"]
    missing = [c for c in required_cols if c not in col_map]
    if missing:
        raise ValueError(f"Missing required columns in {file_path}: {missing}")
    
    # If Security Name header not found, use column left of Ticker
    if "Security Name" not in col_map and ticker_col and ticker_col > 1:
        col_map["Security Name"] = ticker_col - 1
    elif "Security Name" not in col_map:
        col_map["Security Name"] = None  # Will default to empty string
    
    # Parse data rows starting at row 10
    securities = []
    row_num = 10
    
    while True:
        ticker = ws.cell(row=row_num, column=col_map["Ticker"]).value
        
        # Stop at first blank ticker (end of table)
        if ticker is None or str(ticker).strip() == "":
            break
        
        security_name = ws.cell(row=row_num, column=col_map["Security Name"]).value if col_map["Security Name"] else ""
        port_ending_weight = ws.cell(row=row_num, column=col_map["Port. Ending Weight"]).value
        contribution_to_return = ws.cell(row=row_num, column=col_map["Contribution To Return"]).value
        gics = ws.cell(row=row_num, column=col_map["GICS"]).value
        
        # Parse numeric values (handle potential None or string values)
        try:
            weight = float(port_ending_weight) if port_ending_weight is not None else 0.0
        except (ValueError, TypeError):
            weight = 0.0
            
        try:
            contribution = float(contribution_to_return) if contribution_to_return is not None else 0.0
        except (ValueError, TypeError):
            contribution = 0.0
        
        securities.append(SecurityRow(
            ticker=str(ticker).strip(),
            security_name=str(security_name).strip() if security_name else "",
            port_ending_weight=weight,
            contribution_to_return=contribution,
            gics=str(gics).strip() if gics else "NA"
        ))
        
        row_num += 1
    
    wb.close()
    
    # Extract portcode from filename
    portcode = extract_portcode_from_filename(file_path.name)
    
    return PortfolioData(
        portcode=portcode,
        period=period,
        securities=securities,
        source_file=file_path
    )


def parse_multiple_files(file_paths: list[Path]) -> list[PortfolioData]:
    """
    Parse multiple Excel files.
    
    Args:
        file_paths: List of paths to Excel files
        
    Returns:
        List of PortfolioData objects
    """
    results = []
    for file_path in file_paths:
        try:
            data = parse_excel_file(file_path)
            results.append(data)
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            raise
    return results
