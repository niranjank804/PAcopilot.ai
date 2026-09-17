from src.tm1.addressing import is_saas_host, parse_address


def test_bare_hostname_is_unchanged():
    assert parse_address("tm1.example.com").host == "tm1.example.com"


def test_scheme_whitespace_and_trailing_slash_are_removed():
    parsed = parse_address(" https://us-east-1.planninganalytics.saas.ibm.com/ ")

    assert parsed.host == "us-east-1.planninganalytics.saas.ibm.com"
    assert parsed.tenant is None
    assert parsed.database is None


def test_rest_url_yields_tenant_and_database():
    parsed = parse_address(
        "https://eu-central-1.planninganalytics.saas.ibm.com/api/ABC123/v0/tm1/Finance/"
    )

    assert parsed.host == "eu-central-1.planninganalytics.saas.ibm.com"
    assert parsed.tenant == "ABC123"
    assert parsed.database == "Finance"


def test_unrelated_path_is_dropped_without_inventing_fields():
    parsed = parse_address("https://us-east-1.planninganalytics.saas.ibm.com/login")

    assert parsed.host == "us-east-1.planninganalytics.saas.ibm.com"
    assert parsed.tenant is None


def test_saas_host_detection_covers_every_region():
    assert is_saas_host("us-east-1.planninganalytics.saas.ibm.com")
    assert is_saas_host("AP-SOUTHEAST-2.PlanningAnalytics.SaaS.IBM.com")
    assert not is_saas_host("tm1.example.com")
    # A lookalike that merely contains the domain must not match.
    assert not is_saas_host("planninganalytics.saas.ibm.com.attacker.example")
