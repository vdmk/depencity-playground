from agent_runner.docker import docker_build_command, docker_command


def test_docker_command_is_read_only_and_network_disabled(tmp_path):
    target = tmp_path / 'task.py'
    command = docker_command(target, tmp_path, 'python:3.14-slim', None)

    assert command[:5] == ['docker', 'run', '--rm', '--network', 'none']
    assert '--read-only' in command
    assert '--tmpfs' in command
    assert '--cap-drop' in command
    assert '--security-opt' in command
    assert '--user' in command
    assert '-v' in command
    assert command[-2:] == ['python', 'task.py']


def test_docker_command_accepts_container_test_command(tmp_path):
    target = tmp_path / 'task.py'
    command = docker_command(target, tmp_path, 'image', 'python -m py_compile task.py')

    assert command[-4:] == ['python', '-m', 'py_compile', 'task.py']


def test_docker_build_command_allows_network_only_during_build(tmp_path):
    dockerfile = tmp_path / 'Dockerfile.test'
    command = docker_build_command(tmp_path, dockerfile, 'complexity-test:local')

    assert command[:4] == ['docker', 'build', '--network', 'default']
    assert command[4:] == [
        '--file', 'Dockerfile.test',
        '--tag', 'complexity-test:local',
        str(tmp_path),
    ]
