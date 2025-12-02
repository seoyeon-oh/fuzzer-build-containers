#!/usr/bin/python3

"""
This tool manages container images for building Linux kernel fuzzers with Clang and GCC compilers.
Each image is built for a specific compiler (either GCC or Clang), not bundled together.
"""

import os
import subprocess
import sys
import argparse
import pwd
import grp

# Compiler metadata: maps compiler to ubuntu_version
COMPILER_METADATA = {
    'clang-5':  '16.04',
    'clang-6':  '16.04',
    'clang-7':  '18.04',
    'clang-8':  '18.04',
    'clang-9':  '20.04',
    'clang-10': '20.04',
    'clang-11': '20.04',
    'clang-12': '22.04',
    'clang-13': '22.04',
    'clang-14': '22.04',
    'clang-15': '24.04',
    'clang-16': '24.04',
    'clang-17': '24.04',
    'gcc-4.9':  '16.04',
    'gcc-5':    '16.04',
    'gcc-6':    '18.04',
    'gcc-7':    '18.04',
    'gcc-8':    '20.04',
    'gcc-9':    '20.04',
    'gcc-10':   '20.04',
    'gcc-11':   '22.04',
    'gcc-12':   '22.04',
    'gcc-13':   '24.04',
    'gcc-14':   '24.04',
}

SUPPORTED_COMPILERS = list(COMPILER_METADATA.keys()) + ['all']


class ContainerImage:
    """
    Represents a container image for building a Linux kernel fuzzer with a specific compiler.

    Class Attributes:
        runtime (str): container runtime name ('docker' or 'podman')
        runtime_cmd (List): commands for calling the container runtime
        quiet (bool): quiet mode for hiding the container image build log
        fuzzer_name (str): name of the fuzzer
        additional_deps (str): additional apt packages to install

    Instance Attributes:
        compiler (str): compiler identifier (e.g., 'gcc-12', 'clang-15')
        compiler_type (str): 'gcc' or 'clang'
        compiler_version (str): version number of the compiler
        ubuntu (str): Ubuntu version
        tag (str): container image tag
        id (str): container image ID
    """

    runtime = None
    runtime_cmd = None
    quiet = False
    fuzzer_name = None
    additional_deps = None

    def __init__(self, compiler):
        if compiler not in COMPILER_METADATA:
            sys.exit(f'[-] ERROR: Unknown compiler "{compiler}"')

        if not ContainerImage.runtime_cmd:
            ContainerImage.runtime_cmd = self.identify_runtime_cmd()

        self.compiler = compiler
        self.compiler_type, self.compiler_version = compiler.split('-', 1)
        self.ubuntu = COMPILER_METADATA[compiler]
        self.tag = f'fuzzer-build-container:{ContainerImage.fuzzer_name}-{self.compiler}'
        self.id = self.find_id()

    def build(self):
        """Build a container image for the specified compiler"""
        if self.id:
            print(f'\nThe container image for {self.fuzzer_name}-{self.compiler} exists: {self.id}')
            return

        print(f'\nBuilding container image for {self.compiler} (Ubuntu {self.ubuntu})')

        build_args = ['build',
                      '--build-arg', f'UBUNTU_VERSION={self.ubuntu}',
                      '--build-arg', f'UNAME={pwd.getpwuid(os.getuid()).pw_name}',
                      '--build-arg', f'GNAME={grp.getgrgid(os.getgid()).gr_name}',
                      '--build-arg', f'UID={os.getuid()}',
                      '--build-arg', f'GID={os.getgid()}']

        # Only pass the relevant compiler version
        if self.compiler_type == 'gcc':
            build_args += ['--build-arg', f'GCC_VERSION={self.compiler_version}']
        else:
            build_args += ['--build-arg', f'CLANG_VERSION={self.compiler_version}']

        # Add additional dependencies if specified
        if ContainerImage.additional_deps:
            build_args += ['--build-arg', f'ADDITIONAL_DEPS={ContainerImage.additional_deps}']

        build_args += ['-t', self.tag]

        if self.quiet:
            print('[!] INFO: Quiet mode, please wait...')
            build_args += ['-q']

        build_dir = ['.']
        cmd = self.runtime_cmd + build_args + build_dir
        subprocess.run(cmd, text=True, check=True)
        self.id = self.find_id()

    def rm(self):
        """Try to remove the container image if it exists"""
        if not self.id:
            print(f'\nNo container image for {self.compiler}')
            return

        print(f'\nRemoving container image {self.id} for {self.compiler}')

        # We need to get full ID of the container image,
        # since Podman fails to search containers using a short one
        get_full_id_cmd = self.runtime_cmd + ['inspect', f'{self.id}', '--format', '{{.ID}}']
        out = subprocess.run(get_full_id_cmd, text=True, check=True, stdout=subprocess.PIPE)
        full_id = out.stdout.strip()
        assert full_id, f'[-] ERROR: Looks like the image {self.id} is already removed'

        get_containers_cmd = self.runtime_cmd + ['ps', '-a', '--filter', f'ancestor={full_id}',
                                                 '--format', '{{.ID}}']
        out = subprocess.run(get_containers_cmd, text=True, check=True, stdout=subprocess.PIPE)
        running_containers = out.stdout.strip()

        if running_containers:
            print(f'[!] WARNING: Removing the image {self.id} failed, some containers use it')
        else:
            rmi_cmd = self.runtime_cmd + ['rmi', '-f', self.id]
            subprocess.run(rmi_cmd, text=True, check=True)

        # Update id to reflect the changes
        self.id = self.find_id()

    def find_id(self):
        """Find the ID of the container image. Return an empty string if it doesn't exist."""
        find_cmd = self.runtime_cmd + ['images', self.tag, '--format', '{{.ID}}']
        out = subprocess.run(find_cmd, text=True, check=False, capture_output=True)
        if out.returncode != 0:
            sys.exit(f'[-] ERROR: {self.runtime} returned {out.returncode}:\n{out.stderr}')
        image_id = out.stdout.strip()
        if image_id:
            # Fix for the Podman issue (duplicated results)
            return image_id.split()[0]
        return image_id

    def identify_runtime_cmd(self):
        """Identify the commands for working with the container runtime"""
        try:
            cmd = [self.runtime, 'ps']
            out = subprocess.run(cmd, text=True, check=False, capture_output=True)
            if out.returncode == 0:
                return [self.runtime]
            if self.runtime == 'docker' and 'permission denied' in out.stderr:
                print('[!] INFO: We need "sudo" for working with Docker containers')
                return ['sudo', self.runtime]
            sys.exit(f'[-] ERROR: Testing "{" ".join(cmd)}" gives unknown error:\n{out.stderr}')
        except FileNotFoundError:
            sys.exit('[-] ERROR: The container runtime is not installed')


def build_images(needed_compiler, fuzzer_name):
    """Build container images for the specified compiler(s)"""
    if needed_compiler == 'all':
        compilers_to_build = [c for c in COMPILER_METADATA.keys()]
    else:
        compilers_to_build = [needed_compiler]

    for compiler in compilers_to_build:
        image = ContainerImage(compiler)
        image.build()


def remove_images(needed_compiler, fuzzer_name):
    """Remove container images for the specified compiler(s)"""
    if needed_compiler == 'all':
        compilers_to_remove = [c for c in COMPILER_METADATA.keys()]
    else:
        compilers_to_remove = [needed_compiler]

    fail_cnt = 0
    for compiler in compilers_to_remove:
        image = ContainerImage(compiler)
        image.rm()
        if image.id:
            fail_cnt += 1

    if fail_cnt:
        print(f'\n[!] WARNING: failed to remove {fail_cnt} container image(s), see the log above')


def ensure_runtime_cmd():
    """Initialize runtime_cmd if not already set"""
    if not ContainerImage.runtime_cmd:
        try:
            cmd = [ContainerImage.runtime, 'ps']
            out = subprocess.run(cmd, text=True, check=False, capture_output=True)
            if out.returncode == 0:
                ContainerImage.runtime_cmd = [ContainerImage.runtime]
            elif ContainerImage.runtime == 'docker' and 'permission denied' in out.stderr:
                print('[!] INFO: We need "sudo" for working with Docker containers')
                ContainerImage.runtime_cmd = ['sudo', ContainerImage.runtime]
            else:
                sys.exit(f'[-] ERROR: Testing "{" ".join(cmd)}" gives unknown error:\n{out.stderr}')
        except FileNotFoundError:
            sys.exit('[-] ERROR: The container runtime is not installed')


def list_all_images():
    """List all fuzzer-build-container images"""
    ensure_runtime_cmd()

    print('\nAll fuzzer-build-container images:')
    print('-' * 70)
    print(f' {"Tag":<50} | {"Image ID":<12}')
    print('-' * 70)

    list_cmd = ContainerImage.runtime_cmd + ['images', '--format', '{{.Repository}}:{{.Tag}} {{.ID}}']
    out = subprocess.run(list_cmd, text=True, check=True, stdout=subprocess.PIPE)

    found = False
    for line in out.stdout.strip().split('\n'):
        if line and line.startswith('fuzzer-build-container:'):
            parts = line.split()
            tag = parts[0]
            image_id = parts[1] if len(parts) > 1 else '-'
            print(f' {tag:<50} | {image_id:<12}')
            found = True

    if not found:
        print(' (no images found)')

    print('-' * 70)


def main():
    """The main function for managing the images for fuzzer-build-containers"""
    parser = argparse.ArgumentParser(description='Manage container images for fuzzer-build-containers')
    parser.add_argument('-d', '--docker', action='store_true',
                        help='force to use the Docker container engine (default)')
    parser.add_argument('-p', '--podman', action='store_true',
                        help='force to use the Podman container engine instead of default Docker')
    parser.add_argument('-l', '--list', action='store_true',
                        help='list all fuzzer-build-container images')
    parser.add_argument('-b', '--build', nargs='?', const='all', choices=SUPPORTED_COMPILERS,
                        metavar='compiler',
                        help=f'build a container image for a specific compiler: '
                             f'{" / ".join(SUPPORTED_COMPILERS)} '
                             '("all" builds all images if no compiler is specified)')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='suppress the container image build output (for using with --build)')
    parser.add_argument('-r', '--remove', nargs='?', const='all', choices=SUPPORTED_COMPILERS,
                        metavar='compiler',
                        help=f'remove container images for: {" / ".join(SUPPORTED_COMPILERS)} '
                             '("all" removes all images if no compiler is specified)')
    parser.add_argument('-f', '--fuzzer', type=str, metavar='NAME',
                        help='fuzzer name (required for --build and --remove operations)')
    parser.add_argument('--deps', type=str, metavar='PACKAGES',
                        help='additional apt packages to install, comma-separated '
                             '(optional, for use with --build)')

    args = parser.parse_args()

    if args.podman and args.docker:
        sys.exit('[-] ERROR: Multiple container engines specified')
    if args.docker:
        print('[+] Force to use the Docker container engine')
        ContainerImage.runtime = 'docker'
    elif args.podman:
        print('[+] Force to use the Podman container engine')
        print(f'[!] INFO: Working with Podman images belonging to "{pwd.getpwuid(os.getuid()).pw_name}" (UID {os.getuid()})')
        ContainerImage.runtime = 'podman'
    else:
        print(f'[+] Docker container engine is chosen (default)')
        ContainerImage.runtime = 'docker'

    if not any((args.list, args.build, args.remove)):
        parser.print_help()
        sys.exit(1)

    if bool(args.list) + bool(args.build) + bool(args.remove) > 1:
        sys.exit('[-] ERROR: Invalid combination of options')

    # Validate fuzzer name requirement
    if args.build:
        if not args.fuzzer:
            sys.exit('[-] ERROR: --fuzzer is required for --build operation')
        ContainerImage.fuzzer_name = args.fuzzer

    if args.remove:
        if not args.fuzzer:
            sys.exit('[-] ERROR: --fuzzer is required for --remove operation')
        ContainerImage.fuzzer_name = args.fuzzer

    if args.quiet:
        if not args.build:
            sys.exit('[-] ERROR: "--quiet" should be used only with the "--build" option')
        ContainerImage.quiet = True

    if args.deps:
        if not args.build:
            sys.exit('[-] ERROR: "--deps" should be used only with the "--build" option')
        # Convert comma-separated to space-separated for apt-get
        ContainerImage.additional_deps = args.deps.replace(',', ' ')

    if args.list:
        list_all_images()
        sys.exit(0)

    if args.build:
        build_images(args.build, args.fuzzer)
        list_all_images()
        sys.exit(0)

    if args.remove:
        remove_images(args.remove, args.fuzzer)
        list_all_images()
        sys.exit(0)


if __name__ == '__main__':
    main()
