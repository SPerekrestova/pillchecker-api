"""Tests for dosage regex parser — 20+ real packaging examples."""

from app.nlp.dosage_parser import Dosage, extract_dosages


class TestSimpleDosages:
    def test_ibuprofen_400mg(self):
        result = extract_dosages("Ibuprofen 400 mg Film-Coated Tablets")
        assert len(result) == 1
        assert result[0].value == 400.0
        assert result[0].unit == "mg"

    def test_paracetamol_500mg_no_space(self):
        result = extract_dosages("Paracetamol 500mg tablets")
        assert len(result) == 1
        assert result[0].value == 500.0

    def test_vitamin_d_1000iu(self):
        result = extract_dosages("Vitamin D3 1000 IU capsules")
        assert len(result) == 1
        assert result[0].unit == "IU"

    def test_levothyroxine_50mcg(self):
        result = extract_dosages("Levothyroxine 50 mcg tablets")
        assert len(result) == 1
        assert result[0].value == 50.0
        assert result[0].unit == "mcg"

    def test_metformin_850mg(self):
        result = extract_dosages("Metformin HCl 850 mg")
        assert len(result) == 1
        assert result[0].value == 850.0

    def test_decimal_dosage(self):
        result = extract_dosages("Alprazolam 0.5 mg tablets")
        assert len(result) == 1
        assert result[0].value == 0.5

    def test_amoxicillin_1g(self):
        result = extract_dosages("Amoxicillin 1 g powder")
        assert len(result) == 1
        assert result[0].unit == "g"

    def test_microgram_symbol(self):
        result = extract_dosages("Fentanyl 25 µg/hr patch")
        dosage = [d for d in result if d.unit == "µg"]
        assert len(dosage) >= 1
        assert dosage[0].value == 25.0


class TestCompoundDosages:
    def test_suspension_10mg_5ml(self):
        result = extract_dosages("Ibuprofen 10 mg/5 ml oral suspension")
        compound = [d for d in result if d.per_value is not None]
        assert len(compound) >= 1
        assert compound[0].value == 10.0
        assert compound[0].per_value == 5.0
        assert compound[0].per_unit == "ml"

    def test_concentration_500mg_5ml(self):
        result = extract_dosages("Amoxicillin 500mg/5ml")
        compound = [d for d in result if d.per_value is not None]
        assert len(compound) >= 1
        assert compound[0].value == 500.0

    def test_per_ml(self):
        result = extract_dosages("Insulin 100 IU/ml")
        compound = [d for d in result if d.per_unit is not None]
        assert len(compound) >= 1
        assert compound[0].unit == "IU"

    def test_solution_200mg_ml(self):
        result = extract_dosages("Ibuprofen 200mg/ml drops")
        compound = [d for d in result if d.per_unit is not None]
        assert len(compound) >= 1


class TestPerUnitDosages:
    def test_per_tablet(self):
        result = extract_dosages("500 mg/tablet")
        per_unit = [d for d in result if d.per_unit == "tablet"]
        assert len(per_unit) >= 1
        assert per_unit[0].value == 500.0

    def test_per_capsule(self):
        result = extract_dosages("200 mg/capsule")
        per_unit = [d for d in result if d.per_unit == "capsule"]
        assert len(per_unit) >= 1

    def test_per_dose(self):
        result = extract_dosages("Salbutamol 100 mcg/dose inhaler")
        per_unit = [d for d in result if d.per_unit == "dose"]
        assert len(per_unit) >= 1
        assert per_unit[0].value == 100.0


class TestPercentage:
    def test_cream_1_percent(self):
        result = extract_dosages("Hydrocortisone 1% cream")
        assert any(d.unit == "%" and d.value == 1.0 for d in result)

    def test_decimal_percent(self):
        result = extract_dosages("Betamethasone 0.1% ointment")
        assert any(d.unit == "%" and d.value == 0.1 for d in result)


class TestMultipleDosages:
    def test_combination_drug(self):
        # Co-amoxiclav: two active ingredients
        result = extract_dosages("Amoxicillin 500 mg / Clavulanic Acid 125 mg")
        mg_dosages = [d for d in result if d.unit == "mg"]
        assert len(mg_dosages) >= 2

    def test_real_packaging_brufen(self):
        text = "BRUFEN Ibuprofen 400 mg Film-Coated Tablets"
        result = extract_dosages(text)
        assert len(result) >= 1
        assert result[0].value == 400.0


class TestEdgeCases:
    def test_no_dosage(self):
        result = extract_dosages("Take with food and water")
        assert result == []

    def test_mmol(self):
        result = extract_dosages("Potassium chloride 10 mmol effervescent")
        assert len(result) == 1
        assert result[0].unit == "mmol"
