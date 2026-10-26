import json
import random

ROLES_DB = [
    # BCCFU - IATSE 891
    {
        "guild": "BCCFU",
        "union": "IATSE Local 891",
        "role": "Dolly Operator",
        "rate": 45.98,
        "turnaround": 10.0,
        "t_clause": "BCCFU Article A1.20(a)",
        "m_clause": "BCCFU Article 6.01/6.04",
        "ot_clause": "BCCFU Article 4.06",
    },
    {
        "guild": "BCCFU",
        "union": "IATSE Local 891",
        "role": "Head Lighting Technician",
        "rate": 51.41,
        "turnaround": 10.0,
        "t_clause": "BCCFU Article A1.20(a)",
        "m_clause": "BCCFU Article 6.01/6.04",
        "ot_clause": "BCCFU Article 4.06",
    },
    {
        "guild": "BCCFU",
        "union": "IATSE Local 891",
        "role": "Assistant Costume Designer",
        "rate": 50.15,
        "turnaround": 10.0,
        "t_clause": "BCCFU Article A1.20(a)",
        "m_clause": "BCCFU Article 6.01/6.04",
        "ot_clause": "BCCFU Article 4.06",
    },
    {
        "guild": "BCCFU",
        "union": "IATSE Local 891",
        "role": "Boom Operator",
        "rate": 53.56,
        "turnaround": 10.0,
        "t_clause": "BCCFU Article A1.20(a)",
        "m_clause": "BCCFU Article 6.01/6.04",
        "ot_clause": "BCCFU Article 4.06",
    },
    # BCCFU - Teamsters 155
    {
        "guild": "BCCFU",
        "union": "Teamsters Local Union No. 155",
        "role": "Driver Captain",
        "rate": 45.15,
        "turnaround": 8.0,
        "t_clause": "BCCFU Article B3.01(a)",
        "m_clause": "BCCFU Article 6.01/6.04",
        "ot_clause": "BCCFU Article 4.06",
    },
    {
        "guild": "BCCFU",
        "union": "Teamsters Local Union No. 155",
        "role": "Special Equipment Driver",
        "rate": 44.77,
        "turnaround": 8.0,
        "t_clause": "BCCFU Article B3.01(a)",
        "m_clause": "BCCFU Article 6.01/6.04",
        "ot_clause": "BCCFU Article 4.06",
    },
    # DGC BC
    {
        "guild": "DGC",
        "union": "DGC BC",
        "role": "Third Assistant Director",
        "rate": 29.61,
        "turnaround": 9.0,
        "t_clause": "DGC BC Article 17.1",
        "m_clause": "DGC BC Article 16.2",
        "ot_clause": "DGC BC Article 15.5",
    },
    {
        "guild": "DGC",
        "union": "DGC BC",
        "role": "Assistant Location Manager",
        "rate": 36.05,
        "turnaround": 9.0,
        "t_clause": "DGC BC Article 17.1",
        "m_clause": "DGC BC Article 16.2",
        "ot_clause": "DGC BC Article 15.5",
    },
    # UBCP / ACTRA
    {
        "guild": "UBCP",
        "union": "UBCP/ACTRA",
        "role": "Principal Actor",
        "rate": 114.71,
        "turnaround": 11.0,
        "t_clause": "UBCP BCMPA Article A1301",
        "m_clause": "UBCP BCMPA Article A1401",
        "ot_clause": "UBCP BCMPA Article A1201",
    },
    {
        "guild": "UBCP",
        "union": "UBCP/ACTRA",
        "role": "Stunt Performer",
        "rate": 114.71,
        "turnaround": 11.0,
        "t_clause": "UBCP BCMPA Article A1301",
        "m_clause": "UBCP BCMPA Article A1401",
        "ot_clause": "UBCP BCMPA Article A1201",
    },
]

PROMPT_TEMPLATES = [
    "Production Audit Request:\n- Guild: {guild} ({union})\n- Role: {role}\n- Rate: ${rate}/hr\n- Total Elapsed Work Time: {hours}h\n- First Meal Given: {meal_time}h after call\n- Rest Period Between Shifts: {rest}h\nPlease audit this shift.",
    "Can you check if there are any contractual violations for this shift?\nWorker: {role} ({union})\nHourly base: ${rate}\nTotal hours logged: {hours} hours\nMeal break called: {meal_time} hours after call time\nTurnaround given: {rest} hours before next call",
    "Please audit the following film crew timecard:\nRole: {role} under {guild}\nScale wage: ${rate}/hr\nShift duration: {hours}h\nFirst meal break: {meal_time}h mark\nRest period: {rest}h",
]


def generate_entry():
  item = random.choice(ROLES_DB)
  hours = round(random.uniform(7.5, 17.0), 1)
  meal_time = round(random.uniform(5.0, 8.5), 1)
  rest = round(random.uniform(5.0, 12.0), 1)

  violations = []

  # 1. Daily Maximum / Excessive Hours
  if item["guild"] in ["BCCFU", "DGC"] and hours > 15.0:
    excess = round(hours - 15.0, 1)
    violations.append({
        "violation_type": "Extended Workday (>15 Hours)",
        "clause": item["ot_clause"],
        "description": (
            f"Worker logged {hours} hours. Work past 15 consecutive hours"
            " requires extended workday premium pay (2.5x to 3.0x base rate)."
        ),
        "hours_affected": excess,
    })
  elif item["guild"] == "UBCP" and hours > 12.0:
    excess = round(hours - 12.0, 1)
    violations.append({
        "violation_type": "Excessive Performer Hours (>12h Double Time)",
        "clause": item["ot_clause"],
        "description": (
            f"Performer worked {hours} hours. Hours past 12 must be compensated"
            " at 2.0x contracted hourly rate."
        ),
        "hours_affected": excess,
    })

  # 2. Turnaround Encroachment
  if rest < item["turnaround"]:
    encroached = round(item["turnaround"] - rest, 1)
    violations.append({
        "violation_type": "Turnaround Encroachment",
        "clause": item["t_clause"],
        "description": (
            f"Rest period of {rest}h fails to meet mandatory minimum of"
            f" {item['turnaround']}h. Encroached by {encroached} hours."
        ),
        "hours_affected": encroached,
    })

  # 3. Meal Penalties
  if meal_time > 6.0:
    delay = round(meal_time - 6.0, 1)
    violations.append({
        "violation_type": "Delayed Meal Penalty",
        "clause": item["m_clause"],
        "description": (
            f"First meal was provided at {meal_time}h after call, exceeding the"
            " mandatory 6-hour window."
        ),
        "hours_affected": delay,
    })

  template = random.choice(PROMPT_TEMPLATES)
  user_prompt = template.format(
      guild=item["guild"],
      union=item["union"],
      role=item["role"],
      rate=item["rate"],
      hours=hours,
      meal_time=meal_time,
      rest=rest,
  )

  assistant_output = {
      "agreement": item["guild"],
      "classification": item["role"],
      "is_compliant": len(violations) == 0,
      "violations": violations,
  }

  return {
      "messages": [
          {
              "role": "system",
              "content": (
                  "You are a specialized British Columbia Film & Television"
                  " Labor Compliance Assistant. Analyze timesheets and shift"
                  " reports against BC collective agreements and output"
                  " structured JSON audits."
              ),
          },
          {"role": "user", "content": user_prompt},
          {
              "role": "assistant",
              "content": (
                  f"```json\n{json.dumps(assistant_output, indent=2)}\n```"
              ),
          },
      ]
  }


def generate_and_split(
    total_samples=500,
    train_ratio=0.8,
    train_file="train.jsonl",
    eval_file="eval.jsonl",
    seed=42,
):
  random.seed(seed)

  data = [generate_entry() for _ in range(total_samples)]
  random.shuffle(data)

  split_idx = int(total_samples * train_ratio)
  train_data = data[:split_idx]
  eval_data = data[split_idx:]

  with open(train_file, "w", encoding="utf-8") as f:
    for entry in train_data:
      f.write(json.dumps(entry) + "\n")

  with open(eval_file, "w", encoding="utf-8") as f:
    for entry in eval_data:
      f.write(json.dumps(entry) + "\n")

  print(f"Generated {total_samples} samples.")
  print(f"• Training set: {len(train_data)} samples written to '{train_file}'")
  print(f"• Evaluation set: {len(eval_data)} samples written to '{eval_file}'")


if __name__ == "__main__":
  generate_and_split(
      total_samples=500,
      train_ratio=0.8,
      train_file="train.jsonl",
      eval_file="eval.jsonl",
  )
