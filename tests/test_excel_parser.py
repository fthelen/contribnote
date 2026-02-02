"""
Tests for the Excel Parser Module.
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from src.excel_parser import (
    SecurityRow,
    PortfolioData,
    extract_portcode_from_filename,
    parse_excel_file,
    parse_multiple_files,
)


# --- SecurityRow Tests ---

class TestSecurityRow:
    """Tests for the SecurityRow dataclass."""

    def test_is_cash_or_fee_with_na_gics(self):
        """Should identify NA GICS as cash/fee row."""
        row = SecurityRow(
            ticker="FEE_USD",
            security_name="Fee",
            port_ending_weight=0.0,
            contribution_to_return=-0.01,
            gics="NA"
        )
        assert row.is_cash_or_fee() is True

    def test_is_cash_or_fee_with_none_gics(self):
        """Should identify None GICS as cash/fee row."""
        row = SecurityRow(
            ticker="CASH",
            security_name="Cash",
            port_ending_weight=1.0,
            contribution_to_return=0.0,
            gics=None
        )
        assert row.is_cash_or_fee() is True

    def test_is_cash_or_fee_with_valid_gics(self):
        """Should not identify valid GICS as cash/fee row."""
        row = SecurityRow(
            ticker="AAPL",
            security_name="Apple Inc.",
            port_ending_weight=5.25,
            contribution_to_return=0.15,
            gics="Information Technology"
        )
        assert row.is_cash_or_fee() is False


# --- PortfolioData Tests ---

class TestPortfolioData:
    """Tests for the PortfolioData dataclass."""

    def test_get_filtered_securities_excludes_cash_and_fees(self):
        """Should filter out cash and fee rows."""
        securities = [
            SecurityRow("AAPL", "Apple Inc.", 5.0, 0.15, "Information Technology"),
            SecurityRow("FEE_USD", "Fee", 0.0, -0.01, "NA"),
            SecurityRow("MSFT", "Microsoft Corp.", 4.0, 0.10, "Information Technology"),
            SecurityRow("CASH", "Cash", 1.0, 0.0, None),
        ]
        portfolio = PortfolioData(
            portcode="TEST",
            period="12/31/2025 to 1/28/2026",
            securities=securities,
            source_file=Path("TEST_12312025_01282026.xlsx")
        )
        
        filtered = portfolio.get_filtered_securities()
        
        assert len(filtered) == 2
        assert filtered[0].ticker == "AAPL"
        assert filtered[1].ticker == "MSFT"

    def test_get_filtered_securities_empty_list(self):
        """Should handle empty securities list."""
        portfolio = PortfolioData(
            portcode="EMPTY",
            period="12/31/2025 to 1/28/2026",
            securities=[],
            source_file=Path("EMPTY_12312025_01282026.xlsx")
        )
        
        filtered = portfolio.get_filtered_securities()
        
        assert filtered == []

    def test_get_filtered_securities_all_excluded(self):
        """Should return empty when all rows are cash/fees."""
        securities = [
            SecurityRow("FEE_USD", "Fee", 0.0, -0.01, "NA"),
            SecurityRow("CASH", "Cash", 1.0, 0.0, None),
        ]
        portfolio = PortfolioData(
            portcode="ALLFEES",
            period="12/31/2025 to 1/28/2026",
            securities=securities,
            source_file=Path("ALLFEES_12312025_01282026.xlsx")
        )
        
        filtered = portfolio.get_filtered_securities()
        
        assert filtered == []


# --- extract_portcode_from_filename Tests ---

class TestExtractPortcodeFromFilename:
    """Tests for the extract_portcode_from_filename function."""

    def test_standard_filename_pattern(self):
        """Should extract portcode from standard pattern."""
        filename = "PORTABC_12312025_01282026.xlsx"
        assert extract_portcode_from_filename(filename) == "PORTABC"

    def test_numeric_portcode(self):
        """Should extract numeric portcode."""
        filename = "1_12312025_01282026.xlsx"
        assert extract_portcode_from_filename(filename) == "1"

    def test_alphanumeric_portcode(self):
        """Should extract alphanumeric portcode."""
        filename = "PORT123ABC_data_01282026.xlsx"
        assert extract_portcode_from_filename(filename) == "PORT123ABC"

    def test_no_underscore_in_filename(self):
        """Should return full stem if no underscore present."""
        filename = "singlename.xlsx"
        assert extract_portcode_from_filename(filename) == "singlename"

    def test_path_with_directories(self):
        """Should handle full path and extract from filename only."""
        filename = "/path/to/files/TESTPORT_12312025_01282026.xlsx"
        assert extract_portcode_from_filename(filename) == "TESTPORT"

    def test_empty_portcode_with_leading_underscore(self):
        """Should return empty string if filename starts with underscore."""
        filename = "_12312025_01282026.xlsx"
        assert extract_portcode_from_filename(filename) == ""


# --- parse_excel_file Tests ---

class TestParseExcelFile:
    """Tests for the parse_excel_file function using mocked openpyxl."""

    def _create_mock_worksheet(self, period, headers, data_rows):
        """Helper to create a mock worksheet with specified data."""
        ws = MagicMock()
        ws.max_column = len(headers) + 1
        
        def cell_side_effect(row, column):
            cell = MagicMock()
            if row == 6 and column == 1:
                cell.value = period
            elif row == 7:
                # Headers in row 7
                if 1 <= column <= len(headers):
                    cell.value = headers[column - 1]
                else:
                    cell.value = None
            elif row >= 10:
                # Data rows
                data_row_idx = row - 10
                if data_row_idx < len(data_rows):
                    if 1 <= column <= len(data_rows[data_row_idx]):
                        cell.value = data_rows[data_row_idx][column - 1]
                    else:
                        cell.value = None
                else:
                    cell.value = None
            else:
                cell.value = None
            return cell
        
        ws.cell = MagicMock(side_effect=cell_side_effect)
        return ws

    def test_parse_valid_excel_file(self):
        """Should parse a valid Excel file correctly."""
        headers = ["Security Name", "Ticker", "Port. Ending Weight", "Contribution To Return", "GICS"]
        data_rows = [
            ["Apple Inc.", "AAPL", 5.25, 0.15, "Information Technology"],
            ["Microsoft Corp.", "MSFT", 4.10, 0.10, "Information Technology"],
            [None, None, None, None, None],  # End of data marker
        ]
        
        mock_ws = self._create_mock_worksheet(
            period="12/31/2025 to 1/28/2026",
            headers=headers,
            data_rows=data_rows
        )
        
        mock_wb = MagicMock()
        mock_wb.sheetnames = ["ContributionMasterRisk"]
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)
        
        with patch('src.excel_parser.openpyxl.load_workbook', return_value=mock_wb):
            result = parse_excel_file(Path("TEST_12312025_01282026.xlsx"))
        
        assert result.portcode == "TEST"
        assert result.period == "12/31/2025 to 1/28/2026"
        assert len(result.securities) == 2
        assert result.securities[0].ticker == "AAPL"
        assert result.securities[0].security_name == "Apple Inc."
        assert result.securities[0].port_ending_weight == 5.25
        assert result.securities[0].contribution_to_return == 0.15

    def test_parse_file_missing_sheet_raises_error(self):
        """Should raise ValueError if required sheet is missing."""
        mock_wb = MagicMock()
        mock_wb.sheetnames = ["OtherSheet"]
        
        with patch('src.excel_parser.openpyxl.load_workbook', return_value=mock_wb):
            with pytest.raises(ValueError, match="Required sheet 'ContributionMasterRisk' not found"):
                parse_excel_file(Path("test.xlsx"))

    def test_parse_file_missing_period_raises_error(self):
        """Should raise ValueError if period is missing from row 6."""
        mock_ws = self._create_mock_worksheet(
            period=None,
            headers=["Ticker", "Security Name", "Port. Ending Weight", "Contribution To Return", "GICS"],
            data_rows=[]
        )
        
        mock_wb = MagicMock()
        mock_wb.sheetnames = ["ContributionMasterRisk"]
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)
        
        with patch('src.excel_parser.openpyxl.load_workbook', return_value=mock_wb):
            with pytest.raises(ValueError, match="Period not found in row 6"):
                parse_excel_file(Path("test.xlsx"))

    def test_parse_file_missing_required_columns_raises_error(self):
        """Should raise ValueError if required columns are missing."""
        headers = ["Security Name", "Ticker"]  # Missing required columns
        
        mock_ws = self._create_mock_worksheet(
            period="12/31/2025 to 1/28/2026",
            headers=headers,
            data_rows=[]
        )
        
        mock_wb = MagicMock()
        mock_wb.sheetnames = ["ContributionMasterRisk"]
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)
        
        with patch('src.excel_parser.openpyxl.load_workbook', return_value=mock_wb):
            with pytest.raises(ValueError, match="Missing required columns"):
                parse_excel_file(Path("test.xlsx"))

    def test_parse_file_handles_invalid_numeric_values(self):
        """Should handle invalid numeric values gracefully."""
        headers = ["Security Name", "Ticker", "Port. Ending Weight", "Contribution To Return", "GICS"]
        data_rows = [
            ["Apple Inc.", "AAPL", "invalid", "not a number", "Tech"],
            [None, None, None, None, None],
        ]
        
        mock_ws = self._create_mock_worksheet(
            period="12/31/2025 to 1/28/2026",
            headers=headers,
            data_rows=data_rows
        )
        
        mock_wb = MagicMock()
        mock_wb.sheetnames = ["ContributionMasterRisk"]
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)
        
        with patch('src.excel_parser.openpyxl.load_workbook', return_value=mock_wb):
            result = parse_excel_file(Path("TEST_12312025_01282026.xlsx"))
        
        # Invalid values should default to 0.0
        assert result.securities[0].port_ending_weight == 0.0
        assert result.securities[0].contribution_to_return == 0.0

    def test_parse_file_stops_at_blank_ticker(self):
        """Should stop reading at first blank ticker row."""
        headers = ["Security Name", "Ticker", "Port. Ending Weight", "Contribution To Return", "GICS"]
        data_rows = [
            ["Apple Inc.", "AAPL", 5.0, 0.15, "Tech"],
            ["", "", 0.0, 0.0, ""],  # Blank ticker - should stop here
            ["Microsoft", "MSFT", 4.0, 0.10, "Tech"],  # Should not be read
        ]
        
        mock_ws = self._create_mock_worksheet(
            period="12/31/2025 to 1/28/2026",
            headers=headers,
            data_rows=data_rows
        )
        
        mock_wb = MagicMock()
        mock_wb.sheetnames = ["ContributionMasterRisk"]
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)
        
        with patch('src.excel_parser.openpyxl.load_workbook', return_value=mock_wb):
            result = parse_excel_file(Path("TEST_12312025_01282026.xlsx"))
        
        assert len(result.securities) == 1
        assert result.securities[0].ticker == "AAPL"


# --- parse_multiple_files Tests ---

class TestParseMultipleFiles:
    """Tests for the parse_multiple_files function."""

    def test_parse_multiple_files_success(self):
        """Should parse multiple files and return list of PortfolioData."""
        mock_data_1 = PortfolioData(
            portcode="PORT1",
            period="12/31/2025 to 1/28/2026",
            securities=[],
            source_file=Path("PORT1_12312025_01282026.xlsx")
        )
        mock_data_2 = PortfolioData(
            portcode="PORT2",
            period="12/31/2025 to 1/28/2026",
            securities=[],
            source_file=Path("PORT2_12312025_01282026.xlsx")
        )
        
        with patch('src.excel_parser.parse_excel_file') as mock_parse:
            mock_parse.side_effect = [mock_data_1, mock_data_2]
            
            results = parse_multiple_files([
                Path("PORT1_12312025_01282026.xlsx"),
                Path("PORT2_12312025_01282026.xlsx")
            ])
        
        assert len(results) == 2
        assert results[0].portcode == "PORT1"
        assert results[1].portcode == "PORT2"

    def test_parse_multiple_files_empty_list(self):
        """Should return empty list for empty input."""
        results = parse_multiple_files([])
        assert results == []

    def test_parse_multiple_files_propagates_error(self):
        """Should propagate errors from parse_excel_file."""
        with patch('src.excel_parser.parse_excel_file') as mock_parse:
            mock_parse.side_effect = ValueError("Test error")
            
            with pytest.raises(ValueError, match="Test error"):
                parse_multiple_files([Path("test.xlsx")])
