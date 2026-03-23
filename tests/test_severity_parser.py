"""Tests for the DrugBank template-aware severity parser."""

from app.nlp.severity_parser import parse_severity


class TestRiskOrSeverityTemplate:
    """'The risk or severity of X can be increased/decreased' → major."""

    def test_bleeding_risk(self):
        desc = "The risk or severity of bleeding can be increased when Aspirin is combined with Warfarin."
        assert parse_severity(desc) == "major"

    def test_adverse_effects(self):
        desc = "The risk or severity of adverse effects can be increased when Drug A is combined with Drug B."
        assert parse_severity(desc) == "major"

    def test_hemorrhage(self):
        desc = "The risk or severity of bleeding and hemorrhage can be increased when Dasatinib is combined with Warfarin."
        assert parse_severity(desc) == "major"

    def test_gastrointestinal_bleeding(self):
        desc = "The risk or severity of gastrointestinal bleeding can be increased when Warfarin is combined with Deferasirox."
        assert parse_severity(desc) == "major"


class TestActivityTemplate:
    """'may increase/decrease the X activities' → moderate/minor."""

    def test_increase_anticoagulant(self):
        desc = "Apixaban may increase the anticoagulant activities of Warfarin."
        assert parse_severity(desc) == "moderate"

    def test_increase_hypotensive(self):
        desc = "Lisinopril may increase the hypotensive activities of Amlodipine."
        assert parse_severity(desc) == "moderate"

    def test_decrease_activities(self):
        desc = "Rifampin may decrease the anticoagulant activities of Warfarin."
        assert parse_severity(desc) == "minor"


class TestConcentrationTemplate:
    """'serum concentration can be increased/decreased' → moderate."""

    def test_concentration_increased(self):
        desc = "The serum concentration of Alfuzosin can be increased when it is combined with Lepirudin."
        assert parse_severity(desc) == "moderate"

    def test_concentration_decreased(self):
        desc = "The serum concentration of Warfarin can be decreased when it is combined with Rifampin."
        assert parse_severity(desc) == "moderate"


class TestMetabolismTemplate:
    """'metabolism can be increased/decreased' → moderate."""

    def test_metabolism_increased(self):
        desc = "The metabolism of Lepirudin can be increased when combined with St. John's Wort."
        assert parse_severity(desc) == "moderate"

    def test_metabolism_decreased(self):
        desc = "The metabolism of Warfarin can be decreased when combined with Fluconazole."
        assert parse_severity(desc) == "moderate"


class TestEfficacyTemplate:
    """'therapeutic efficacy can be decreased' → minor."""

    def test_efficacy_decreased(self):
        desc = "The therapeutic efficacy of Rotavirus vaccine can be decreased when used in combination with Etanercept."
        assert parse_severity(desc) == "minor"


class TestEdgeCases:
    def test_empty_string(self):
        assert parse_severity("") == "unknown"

    def test_none(self):
        assert parse_severity(None) == "unknown"

    def test_unrecognized_template(self):
        desc = "Some completely novel interaction description format."
        assert parse_severity(desc) == "unknown"

    def test_case_insensitive(self):
        desc = "THE RISK OR SEVERITY OF BLEEDING CAN BE INCREASED WHEN ASPIRIN IS COMBINED WITH WARFARIN."
        assert parse_severity(desc) == "major"
