from pathlib import Path
import regex as re
import glob
import sqlite3 as sql

translation_dir = Path("/home/mo/desk/apps/QuranQuizz/chunked_translation")
conn = sql.connect("/home/mo/desk/apps/QuranQuizz/quran.db")
cur = conn.cursor()
sura_number = 0

for i in range(1, 115):
    filename = (
        str(glob.glob(str(translation_dir / f"{i}_*")))
        .replace("[", "")
        .replace("]", "")
    ).replace("'", "")
    with open(filename, "r") as f:
        lines = f.readlines()
        ayah_number = 0
        index = 0
        verse = ""
        for line in lines:
            m = re.match(r"^\d+\.\s", line)
            if m:
                match int(str(m.group(0)).replace(".", "").replace(" ", "")):
                    case 1:
                        print(verse)
                        print(f"{'#'*10} {'First Line':^20} {'#'*10}")
                        verse = line
                        ayah_number = 0
                        ayah_number += 1
                        sura_number += 1
                    case val if val == ayah_number + 1:
                        cur.execute(
                            "UPDATE ayah_metadata_new SET ayah_trans = ? WHERE ayah_number = ? AND sura_number = ?",
                            (
                                verse.replace(f"{ayah_number}. ", ""),
                                ayah_number,
                                sura_number,
                            ),
                        )
                        print(verse)
                        print(f"{'#'*10} {'Next Line':^20} {'#'*10}")
                        verse = line
                        ayah_number += 1
                    case _:
                        RuntimeError("Unexpected")
                        break
            else:
                print(verse)
                verse += line
else:
    conn.commit()
conn.close()
