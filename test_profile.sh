#!/bin/bash
# Simple shell script to test AWS Bedrock inference profile functionality
# with Claude Sonnet 4 model

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}====================================${NC}"
echo -e "${GREEN}AWS Bedrock Inference Profile Tester${NC}"
echo -e "${GREEN}====================================${NC}"

# Check if a profile was specified
if [ -n "$1" ]; then
    PROFILE="$1"
    echo -e "${YELLOW}Using AWS profile: ${PROFILE}${NC}"
else
    PROFILE="bedrock"
    echo -e "${YELLOW}Using default AWS profile: ${PROFILE}${NC}"
fi

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: AWS CLI is not installed. Please install it first.${NC}"
    exit 1
fi

# Check AWS credentials
echo -e "\n${GREEN}Checking AWS credentials...${NC}"
if aws sts get-caller-identity --profile "$PROFILE" &> /dev/null; then
    ACCOUNT_ID=$(aws sts get-caller-identity --profile "$PROFILE" --query "Account" --output text)
    echo -e "${GREEN}✓ AWS credentials valid for account: ${ACCOUNT_ID}${NC}"
else
    echo -e "${RED}✗ AWS credentials invalid or not found for profile: ${PROFILE}${NC}"
    echo -e "${YELLOW}Please check your AWS credentials in ~/.aws/credentials${NC}"
    exit 1
fi

# Check AWS region
AWS_REGION=$(aws configure get region --profile "$PROFILE" || echo "us-west-2")
echo -e "${GREEN}Using AWS region: ${AWS_REGION}${NC}"

# Run the Python test script
echo -e "\n${GREEN}Testing inference profile with Python script...${NC}"
python3 test_inference_profile.py --profile "$PROFILE"

echo -e "\n${GREEN}====================================${NC}"
echo -e "${GREEN}Test completed${NC}"
echo -e "${GREEN}====================================${NC}"
echo -e "${YELLOW}If you encounter any issues, please check:${NC}"
echo -e "1. That you have access to AWS Bedrock in your account"
echo -e "2. That you have created inference profiles for Claude Sonnet 4"
echo -e "3. That your AWS credentials have the right permissions"
echo -e "\n${GREEN}For more information, see the README.md file.${NC}"
