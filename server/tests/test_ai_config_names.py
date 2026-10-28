from app.ai_config import AiConfig, load_ai_config, save_ai_config


def test_names_default_empty_and_old_files_load(tmp_path):
    path = tmp_path / "ai.json"
    path.write_text('{"project_repos": {"ab": "/x"}}')
    config = load_ai_config(path)
    assert config.project_names == {} and config.project_repos == {"AB": "/x"}


def test_names_are_cleaned_and_round_trip(tmp_path):
    path = tmp_path / "ai.json"
    config = AiConfig(project_names={" ab ": " My App ", "cd": "  ", "": "x"})
    assert config.project_names == {"AB": "My App"}
    save_ai_config(path, config)
    assert load_ai_config(path).project_names == {"AB": "My App"}
