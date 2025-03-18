from pathlib import Path
import json
import jq


def main():
    """Does the same as 'jupyter nbconvert --clear-output' but also clears widget state"""

    for notebook in Path("./notebooks/").glob("*.ipynb"):
        with open(notebook, "r+") as f:
            text = f.read()
            out = (
                jq.compile(
                    """
                        (.cells.[] | select(has("outputs")) | .outputs) |= [] | 
                        (.cells.[] | select(has("execution_count")) | .execution_count) |= null |
                        .metadata.widgets.[]?.state |= {}
                    """
                )
                .input_text(text)
                .first()
            )
            f.seek(0)
            json.dump(out, f, indent=1)
            f.write("\n")  # Avoid diff at the last line
            f.truncate()


if __name__ == "__main__":
    main()
