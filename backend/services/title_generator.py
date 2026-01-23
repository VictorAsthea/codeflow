import asyncio
from backend.services.claude_runner import find_claude_cli


async def generate_title(description: str) -> str:
    """
    Generate task title from description using Claude

    Args:
        description: Task description text

    Returns:
        Generated title (max 60 characters)
    """
    claude_path = find_claude_cli()

    prompt = f"""Generate a concise task title (max 60 chars) from this description:

{description}

Output ONLY the title, nothing else."""

    try:
        process = await asyncio.create_subprocess_exec(
            claude_path,
            "--print",
            "--model", "claude-sonnet-4-5-20250929",
            "--max-turns", "1",
            "--permission-mode", "bypassPermissions",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(prompt.encode()),
            timeout=15.0
        )

        title = stdout.decode().strip()

        if not title:
            return extract_title_from_description(description)

        title = title.replace('"', '').replace("'", '')
        return title[:60]

    except asyncio.TimeoutError:
        return extract_title_from_description(description)
    except Exception as e:
        print(f"[ERROR] Failed to generate title: {e}")
        return extract_title_from_description(description)


def extract_title_from_description(description: str) -> str:
    """Fallback: Extract first sentence or first 60 chars as title"""
    lines = description.strip().split('\n')
    first_line = lines[0] if lines else description

    if len(first_line) <= 60:
        return first_line

    return first_line[:57] + "..."
