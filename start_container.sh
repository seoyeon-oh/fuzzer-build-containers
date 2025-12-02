#!/bin/bash

set -eu

print_help() {
	echo "usage: $0 fuzzer_name compiler fuzzer_src_dir out_dir [-h] [-d | -p] [-n] [-k kernel_src_dir] [-e VAR] [-v] [-- cmd with args]"
	echo ""
	echo "Required arguments:"
	echo "  fuzzer_name     name of the fuzzer (used in image tag)"
	echo "  compiler        compiler to use (e.g., gcc-12, clang-15)"
	echo "  fuzzer_src_dir  path to fuzzer source directory (mounted at /fuzzer_src, default workdir)"
	echo "  out_dir         path to output directory (mounted at /out)"
	echo ""
	echo "Optional arguments:"
	echo "  -h    print this help"
	echo "  -d    force to use the Docker container engine (default)"
	echo "  -p    force to use the Podman container engine instead of default Docker"
	echo "  -n    launch container in non-interactive mode"
	echo "  -k    path to kernel source directory (mounted at /src)"
	echo "  -e    add environment variable in the container (may be used multiple times)"
	echo "  -v    enable debug output"
	echo ""
	echo "  If cmd is empty, we will start an interactive bash in the container."
}

if [ $# -lt 4 ]; then
	print_help
	exit 1
fi

FUZZER_NAME="$1"
COMPILER="$2"
FUZZER_SRC="$3"
OUT="$4"
shift 4

# defaults
CIDFILE=""
ENV=""
INTERACTIVE="-it"
KERNEL_SRC=""
RUNTIME=""
RUNTIME_SPECIFIC_ARGS=""
SUDO_CMD=""

while [[ $# -gt 0 ]]; do
	case $1 in
	-h | --help)
		print_help
		exit 0
		;;
	-d | --docker)
		if [ "$RUNTIME" != "" ]; then
			echo "[-] ERROR: Multiple container engines specified" >&2
			exit 1
		else
			echo "Force to use the Docker container engine"
			RUNTIME="docker"
		fi
		shift
		;;
	-p | --podman)
		if [ "$RUNTIME" != "" ]; then
			echo "[-] ERROR: Multiple container engines specified" >&2
			exit 1
		else
			echo "Force to use the Podman container engine"
			echo "[!] INFO: Working with Podman images belonging to \"$(id -un)\" (UID $(id -u))"
			RUNTIME="podman"
			RUNTIME_SPECIFIC_ARGS="--userns=keep-id"
		fi
		shift
		;;
	-n | --non-interactive)
		INTERACTIVE=""
		CIDFILE="--cidfile $OUT/container.id"
		echo "Gonna run the container in NON-interactive mode"
		shift
		;;
	-k | --kernel-src)
		KERNEL_SRC="$2"
		shift 2
		;;
	-e | --env)
		# `set -eu` will prevent out-of-bounds access
		ENV="$ENV -e $2"
		shift 2
		;;
	-v | --verbose)
		set -x
		shift
		;;
	--)
		shift
		break
		;;
	*)
		echo "[-] ERROR: Unknown option $1"
		print_help
		exit 1
		;;
	esac
done

if [ -z "$RUNTIME" ]; then
	echo "Docker container engine is chosen (default)"
	RUNTIME="docker"
fi

set +e
RUNTIME_TEST_OUTPUT="$($RUNTIME ps 2>&1)"
set -e

if echo "$RUNTIME_TEST_OUTPUT" | grep -qi "permission denied"; then
	echo "Hey, we gonna use sudo for running the container"
	SUDO_CMD="sudo"
fi

IMAGE_TAG="fuzzer-build-container:${FUZZER_NAME}-${COMPILER}"
echo "Starting \"$IMAGE_TAG\""

if [ ! -z "$ENV" ]; then
	echo "Container environment arguments: $ENV"
fi

if [ ! -z "$INTERACTIVE" ]; then
	echo "Gonna run the container in interactive mode"
fi

echo "Mount fuzzer source directory \"$FUZZER_SRC\" at \"/fuzzer_src\" (workdir)"
if [ -n "$KERNEL_SRC" ]; then
	echo "Mount kernel source directory \"$KERNEL_SRC\" at \"/src\""
fi
echo "Mount build output directory \"$OUT\" at \"/out\""

if [ $# -gt 0 ]; then
	echo -e "Gonna run command \"$@\"\n"
else
	echo -e "Gonna run bash\n"
fi

# Build volume mount arguments
VOLUME_ARGS="-v $FUZZER_SRC:/fuzzer_src:Z -v $OUT:/out:Z"
if [ -n "$KERNEL_SRC" ]; then
	VOLUME_ARGS="$VOLUME_ARGS -v $KERNEL_SRC:/src:Z"
fi

# Z for setting SELinux label
exec $SUDO_CMD $RUNTIME run $ENV $INTERACTIVE $CIDFILE $RUNTIME_SPECIFIC_ARGS --pull=never --rm \
	$VOLUME_ARGS \
	$IMAGE_TAG "$@"
