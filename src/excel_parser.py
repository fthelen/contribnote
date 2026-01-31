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
    
    # Validate headers in row 7
    expected_headers = ["Ticker", "Security Name", "Port. Ending Weight", 
                        "Contribution To Return", "GICS"]
    actual_headers = [ws.cell(row=7, column=i).value for i in range(1, 6)]
    
    if actual_headers != expected_headers:
        raise ValueError(
            f"Header mismatch in {file_path}. "
            f"Expected: {expected_headers}, Got: {actual_headers}"
        )
    
    # Parse data rows starting at row 10
    securities = []
    row_num = 10
    
    while True:
        ticker = ws.cell(row=row_num, column=1).value
        
        # Stop at first blank ticker (end of table)
        if ticker is None or str(ticker).strip() == "":
            break
        
        security_name = ws.cell(row=row_num, column=2).value
        port_ending_weight = ws.cell(row=row_num, column=3).value
        contribution_to_return = ws.cell(row=row_num, column=4).value
        gics = ws.cell(row=row_num, column=5).value
        
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
