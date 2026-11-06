from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db import Database
from app.models import ParsedItem
from app.services import allocation as alloc
from app.services.invoice_builder import build_invoice_data
from app.services.invoice_export import InvoiceData, InvoiceLine, export_invoices
from app.services.rab_parser import (
    ROLE_NAME,
    ROLE_PRICE,
    ROLE_TERM,
    ROLE_TOTAL_QTY,
    ROLE_UNIT,
    RabMapping,
    MappedColumn,
    _round_qty,
    detect_best_header,
    parse_rab,
    to_number,
)
from app.services.validation import validate_project, validate_term

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "resources" / "invoice_template.xlsx"
SAMPLE_RAB = ROOT / "sample" / "rab_sample.xlsx"
SAMPLE_REAL = ROOT / "sample" / "rab_sample_real.xlsx"


class AllocationTests(unittest.TestCase):
    def test_divisible(self):
        self.assertEqual(alloc.split_qty(10, 5), (2, 0))
        self.assertEqual(
            alloc.allocate_item(10, [1, 2, 3, 4, 5]),
            {1: 2, 2: 2, 3: 2, 4: 2, 5: 2},
        )

    def test_remainder_suggestion_prefers_least_history(self):
        vehicles = [1, 2, 3, 4, 5]
        history = {1: 3, 2: 1, 3: 1, 4: 0, 5: 2}
        result = alloc.allocate_item(4, vehicles, history=history)
        self.assertEqual(sum(result.values()), 4)
        self.assertEqual(result[4], 1)
        self.assertEqual(result[1], 0)

    def test_choice_validation(self):
        plan = alloc.build_remainder_plan(10, 4, [1, 2, 3, 4, 5], history={4: 0, 1: 2})
        self.assertEqual(plan.base, 0)
        self.assertEqual(plan.remainder, 4)
        self.assertEqual(len(plan.suggested), 4)
        self.assertIsNotNone(alloc.validate_choice(plan, list(plan.suggested)[:3]))
        self.assertIsNone(alloc.validate_choice(plan, list(plan.suggested)))
        result = alloc.allocations_for_choice(plan, list(plan.suggested))
        self.assertEqual(sum(result.values()), 4)


class NumberParsingTests(unittest.TestCase):
    def test_indonesian_formats(self):
        self.assertEqual(to_number("1.000.000"), 1_000_000)
        self.assertEqual(to_number("1,5"), 1.5)
        self.assertEqual(to_number("Rp 240.000"), 240_000)
        self.assertEqual(to_number("1.000,50"), 1000.5)
        self.assertEqual(to_number("1,000.50"), 1000.5)
        self.assertIsNone(to_number("-"))
        self.assertEqual(to_number(4), 4.0)


class RoundingTests(unittest.TestCase):
    def test_qty_round_half_up(self):
        self.assertEqual(_round_qty(2.4), 2)
        self.assertEqual(_round_qty(2.5), 3)
        self.assertEqual(_round_qty(2.6), 3)
        self.assertEqual(_round_qty(3.5), 4)


class RabParserTests(unittest.TestCase):
    def test_detect_and_parse_sample(self):
        import openpyxl

        wb = openpyxl.load_workbook(SAMPLE_RAB, data_only=True)
        row, columns = detect_best_header(wb["RAB"])
        self.assertEqual(row, 5)
        roles = {c.role for c in columns}
        self.assertIn(ROLE_NAME, roles)
        self.assertIn(ROLE_PRICE, roles)
        self.assertEqual(sum(1 for c in columns if c.role == ROLE_TERM), 4)

        mapping = RabMapping(sheet="RAB", header_row=row, columns=columns)
        result = parse_rab(SAMPLE_RAB, mapping)
        self.assertEqual(len(result.items), 12)
        self.assertEqual(result.term_names, ["Termin 1", "Termin 2", "Termin 3", "Termin 4"])
        service = result.items[0]
        self.assertEqual(service.name, "Service")
        self.assertEqual(service.unit_price, 240_000)
        self.assertEqual(service.total_qty, 20)
        self.assertEqual(service.term_qty, [5, 5, 5, 5])
        self.assertEqual(result.issues, [])

    def test_manual_mapping_no_term(self):
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Nama", "Satuan", "Harga", "Volume"])
        ws.append(["Oli", "liter", 100000, 7])
        path = Path(tempfile.gettempdir()) / "rab_no_term.xlsx"
        wb.save(path)
        columns = [
            MappedColumn(1, ROLE_NAME),
            MappedColumn(2, ROLE_UNIT),
            MappedColumn(3, ROLE_PRICE),
            MappedColumn(4, ROLE_TOTAL_QTY),
        ]
        result = parse_rab(path, RabMapping("Sheet", 1, columns, "Termin 1"))
        self.assertEqual(result.term_names, ["Termin 1"])
        self.assertEqual(result.items[0].term_qty, [7])
        self.assertEqual(result.items[0].total_qty, 7)

    def test_parse_multi_vehicle_rab(self):
        import openpyxl

        wb = openpyxl.load_workbook(SAMPLE_REAL, data_only=True)
        row, columns = detect_best_header(wb["Sheet1"])
        self.assertEqual(row, 2)
        self.assertEqual(sum(1 for c in columns if c.role == ROLE_TERM), 2)

        mapping = RabMapping(sheet="Sheet1", header_row=row, columns=columns)
        result = parse_rab(SAMPLE_REAL, mapping)
        self.assertEqual(result.term_names, ["Termin 1", "Termin 2"])
        self.assertEqual(len(result.items), 131)
        self.assertEqual(
            [(g.name, g.unit_count, len(g.items)) for g in result.groups],
            [
                ("YAMAHA VIXION", 3, 18),
                ("YAMAHA SCORPIO", 8, 22),
                ("SUZUKI HAYATE", 30, 47),
                ("KAWASAKI 150 CC", 2, 15),
                ("KAWASAKI 250 CC", 2, 14),
                ("YAMAHA NMAX", 5, 15),
            ],
        )
        self.assertEqual(result.issues, [])
        first = result.groups[0].items[0]
        self.assertEqual(first.name, "Service")
        self.assertEqual(first.term_qty, [3, 3])


class DatabaseAndValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.pid = self.db.create_project(
            "Proyek Uji", client_name="POLRESTA", client_address="Bandung"
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_replace_rab_and_validate(self):
        items = [
            ParsedItem("Service", "unit", 240000, 10, [5, 5], 2),
            ParsedItem("Oli", "liter", 100000, 6, [3, 3], 3),
        ]
        self.db.replace_rab(self.pid, ["Termin 1", "Termin 2"], items)
        self.assertEqual(validate_project(self.db, self.pid), [])
        stored = self.db.list_items(self.pid)
        self.assertEqual(len(stored), 2)
        terms = self.db.list_terms(self.pid)
        self.assertEqual([t.name for t in terms], ["Termin 1", "Termin 2"])

    def test_allocation_invariant(self):
        items = [ParsedItem("Service", "unit", 240000, 5, [2, 3], 2)]
        self.db.replace_rab(self.pid, ["Termin 1", "Termin 2"], items)
        self.db.add_vehicle(self.pid, "D 1 A", "Vixion")
        self.db.add_vehicle(self.pid, "D 2 A", "Vixion")
        term = self.db.list_terms(self.pid)[0]
        item = self.db.list_items(self.pid)[0]
        self.db.set_allocation(term.id, item.id, self.db.list_vehicles(self.pid)[0].id, 1)
        issues = validate_term(self.db, term)
        self.assertEqual(len(issues), 1)
        self.assertIn("Kurang 1", issues[0].message)
        self.db.set_allocation(term.id, item.id, self.db.list_vehicles(self.pid)[1].id, 1)
        self.assertEqual(validate_term(self.db, term), [])

    def test_import_multi_vehicle_rab_creates_groups(self):
        import openpyxl

        wb = openpyxl.load_workbook(SAMPLE_REAL, data_only=True)
        row, columns = detect_best_header(wb["Sheet1"])
        result = parse_rab(
            SAMPLE_REAL, RabMapping("Sheet1", row, columns)
        )
        self.db.replace_rab(
            self.pid, result.term_names, groups=result.groups
        )
        types = self.db.list_vehicle_types(self.pid)
        self.assertEqual(len(types), 6)
        self.assertEqual([t.unit_count for t in types], [3, 8, 30, 2, 2, 5])
        vehicles = self.db.list_vehicles(self.pid)
        self.assertEqual(len(vehicles), 50)
        self.assertTrue(all(not vehicle.plate for vehicle in vehicles))
        self.assertEqual(len(self.db.list_items(self.pid)), 131)
        self.assertEqual(validate_project(self.db, self.pid), [])

        vixion = types[0]
        self.assertEqual(len(self.db.list_items(self.pid, vixion.id)), 18)
        self.assertEqual(len(self.db.list_vehicles(self.pid, vixion.id)), 3)
        first = self.db.list_items(self.pid, vixion.id)[0]
        self.assertEqual(first.type_name, "YAMAHA VIXION")

    def test_po_prefix_per_type_applies_to_all_units(self):
        import openpyxl

        wb = openpyxl.load_workbook(SAMPLE_REAL, data_only=True)
        row, columns = detect_best_header(wb["Sheet1"])
        result = parse_rab(SAMPLE_REAL, RabMapping("Sheet1", row, columns))
        self.db.replace_rab(self.pid, result.term_names, groups=result.groups)

        types = self.db.list_vehicle_types(self.pid)
        self.assertTrue(all(t.po_prefix == "" for t in types))

        # Isi prefix sekali untuk satu jenis kendaraan.
        vixion = types[0]
        self.db.update_vehicle_type_po_prefix(vixion.id, "VXN-")
        self.assertEqual(
            {v.po_prefix for v in self.db.list_vehicles(self.pid, vixion.id)},
            {"VXN-"},
        )
        # Jenis lain tidak ikut berubah.
        self.assertTrue(
            all(
                v.po_prefix == ""
                for t in types[1:]
                for v in self.db.list_vehicles(self.pid, t.id)
            )
        )

        # Invoice unit pertama memakai prefix jenis tersebut.
        term = self.db.list_terms(self.pid)[0]
        item = self.db.list_items(self.pid, vixion.id)[0]
        vehicle = self.db.list_vehicles(self.pid, vixion.id)[0]
        self.db.set_allocation(term.id, item.id, vehicle.id, 1)
        invoice = build_invoice_data(
            self.db, self.db.get_project(self.pid), term, vehicle
        )
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.po_number, f"VXN-{vehicle.display_name}")


class InvoiceExportTests(unittest.TestCase):
    def test_build_invoice_with_many_lines(self):
        lines = [
            InvoiceLine(f"Barang {i}", i, 10_000) for i in range(1, 16)
        ]
        invoice = InvoiceData(
            plate="D 1001 ABC",
            vehicle_type="Yamaha Vixion",
            client_name="POLRESTA BANDUNG",
            client_address="JL BHAYANGKARA NO.1",
            company_name="CV. PANJI PERKASA",
            company_address="Kab. Bandung, Jawa Barat",
            po_number="VXN-D 1001 ABC",
            invoice_date=__import__("datetime").date(2026, 7, 1),
            lines=lines,
            discount_percent=10,
            term_name="Termin 1",
        )
        with tempfile.TemporaryDirectory() as tmp:
            paths = export_invoices(TEMPLATE, [invoice], tmp, mode="files")
            self.assertEqual(len(paths), 1)
            import openpyxl

            wb = openpyxl.load_workbook(paths[0], data_only=False)
            ws = wb.active
            self.assertEqual(ws["A1"].value, "INVOICE")
            self.assertEqual(ws["C1"].value, "CV. PANJI PERKASA")
            self.assertEqual(ws["D6"].value, "D 1001 ABC")
            self.assertEqual(ws["A11"].value, 1)
            self.assertEqual(ws["B11"].value, "Barang 1")
            self.assertEqual(ws["D11"].value, 10_000)
            self.assertEqual(ws["A25"].value, 15)
            self.assertEqual(ws["D25"].value, 150_000)
            subtotal_row = 26
            self.assertEqual(ws[f"C{subtotal_row}"].value, "Sub Total")
            self.assertEqual(ws[f"D{subtotal_row}"].value, 1_200_000)
            self.assertEqual(ws[f"D{subtotal_row + 1}"].value, 10)
            self.assertEqual(ws[f"D{subtotal_row + 2}"].value, 1_080_000)
            self.assertEqual(ws["C31"].value, "Hormat Kami,")
            self.assertEqual(ws["C34"].value, "CV. PANJI PERKASA")
            wb.close()

    def test_build_invoice_short(self):
        invoice = InvoiceData(
            plate="D 2 B",
            vehicle_type="Vixion",
            client_name="Klien",
            client_address="Alamat",
            company_name="CV. PANJI PERKASA",
            company_address="Bandung",
            po_number="VXN-D 2 B",
            invoice_date=__import__("datetime").date(2026, 7, 1),
            lines=[InvoiceLine("Service", 1, 250_000)],
            term_name="Termin 2",
        )
        with tempfile.TemporaryDirectory() as tmp:
            paths = export_invoices(TEMPLATE, [invoice], tmp, mode="files")
            import openpyxl

            wb = openpyxl.load_workbook(paths[0])
            ws = wb.active
            self.assertEqual(ws["A11"].value, 1)
            self.assertEqual(ws["D11"].value, 250_000)
            self.assertEqual(ws["D12"].value, 250_000)  # sub total
            self.assertEqual(ws["C14"].value, "TOTAL")
            self.assertEqual(ws["C17"].value, "Hormat Kami,")
            wb.close()


    def test_workbook_has_rekap_first_sheet(self):
        import datetime

        import openpyxl

        def make_invoice(plate, vehicle_type, po_number):
            return InvoiceData(
                plate=plate,
                vehicle_type=vehicle_type,
                client_name="Klien",
                client_address="Alamat",
                company_name="CV. PANJI PERKASA",
                company_address="Bandung",
                po_number=po_number,
                invoice_date=datetime.date(2026, 7, 1),
                lines=[InvoiceLine("Service", 1, 250_000)],
                term_name="Termin 1",
                project_name="R2 Lantas",
            )

        invoices = [
            make_invoice("D 1 A", "Yamaha Vixion", "VXN-D 1 A"),
            make_invoice("D 2 B", "Suzuki Hayate", "HYT-D 2 B"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            paths = export_invoices(TEMPLATE, invoices, tmp, mode="workbook")
            self.assertEqual(len(paths), 1)
            wb = openpyxl.load_workbook(paths[0])
            self.assertEqual(wb.sheetnames[0], "Rekap")
            self.assertEqual(wb.sheetnames[1], "Pivot Qty")
            self.assertEqual(len(wb.sheetnames), len(invoices) + 2)
            ws = wb["Rekap"]
            self.assertEqual(ws["A1"].value, "Rekap R2 Lantas (Termin 1)")
            self.assertEqual(ws["A2"].value, "No")
            self.assertEqual(ws["B3"].value, "VXN-D 1 A")
            self.assertEqual(ws["E3"].value, "Yamaha Vixion")
            self.assertEqual(ws["B4"].value, "HYT-D 2 B")
            self.assertEqual(ws["A5"].value, "TOTAL")
            self.assertEqual(ws["F5"].value, 500_000)
            wb.close()


if __name__ == "__main__":
    unittest.main()
