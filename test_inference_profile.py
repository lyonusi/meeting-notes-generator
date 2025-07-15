#!/usr/bin/env python3
"""
Test script to verify inference profile handling for Claude Sonnet 4 model.

This script demonstrates how to use AWS Bedrock with Claude Sonnet 4 models
that require inference profiles. It checks for available profiles in your
AWS account and attempts to use them for a simple generation task.

Run this script to verify your inference profile setup:
python test_inference_profile.py
"""

import json
import logging
import argparse
from aws_services import AWSHandler
from config import BEDROCK_MODEL_ID, AWS_REGION

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def test_inference_profiles(aws_profile='bedrock', model_id=None):
    """Test inference profile functionality.
    
    Args:
        aws_profile: AWS profile to use (default: 'bedrock')
        model_id: Specific model ID to test (default: use config value)
    """
    # Initialize the AWS handler with the specified profile
    handler = AWSHandler(bedrock_profile=aws_profile)
    
    # Use specified model or default from config
    test_model_id = model_id or BEDROCK_MODEL_ID
    
    logger.info(f"Testing inference profile for model: {test_model_id}")
    logger.info(f"AWS Region: {AWS_REGION}")
    logger.info(f"AWS Account ID: {handler.aws_account_id}")
    
    # 1. Display all available inference profiles
    logger.info("=== Available Inference Profiles ===")
    profiles = handler.get_inference_profiles()
    
    if not profiles:
        logger.warning("No inference profiles found in this AWS account")
    else:
        for i, profile in enumerate(profiles, 1):
            profile_arn = profile.get('inferenceProfileArn', 'N/A')
            model_id = profile.get('modelId', 'N/A')
            
            # Extract account ID from ARN for verification
            account_id = "unknown"
            if profile_arn.startswith("arn:aws:"):
                parts = profile_arn.split(":")
                if len(parts) > 4:
                    account_id = parts[4]
            
            # Print profile details
            logger.info(f"Profile #{i}:")
            logger.info(f"  ARN: {profile_arn}")
            logger.info(f"  Model: {model_id}")
            logger.info(f"  Account: {account_id}")
            logger.info("")
    
    # 2. Check for specific model profile
    logger.info(f"=== Inference Profile for {test_model_id} ===")
    profile_arn = handler.get_inference_profile_for_model(test_model_id)
    
    if profile_arn:
        logger.info(f"Found inference profile: {profile_arn}")
    else:
        logger.warning(f"No inference profile found for {test_model_id}")
        
        # Try to dynamically construct one
        logger.info("Attempting to dynamically construct ARN...")
        if handler.aws_account_id:
            arn = f"arn:aws:bedrock:{AWS_REGION}:{handler.aws_account_id}:inference-profile/us.{test_model_id}"
            logger.info(f"Constructed ARN: {arn}")
            logger.info("Note: This ARN may not be valid if the inference profile doesn't exist")
        else:
            logger.warning("Cannot construct ARN without AWS account ID")
    
    # 3. Test simple generation with the model using inference profile
    logger.info("=== Testing Model Generation with Inference Profile ===")
    try:
        # Simple prompt for testing
        prompt = "Write a one-sentence summary of what makes Claude Sonnet 4 different from previous models."
        
        # Simplified test data structure mimicking a transcript
        test_data = {
            "results": {
                "transcripts": [{"transcript": prompt}]
            }
        }
        
        result = handler.generate_meeting_notes(test_data, test_model_id)
        
        if result:
            logger.info("Generation successful! Result:")
            print("\n---Generation Result---\n")
            print(result[:500] + "..." if len(result) > 500 else result)
            print("\n---------------------\n")
        else:
            logger.error("Generation returned no result")
    
    except Exception as e:
        logger.error(f"Error during generation test: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test inference profile functionality")
    parser.add_argument("--profile", default="bedrock", help="AWS profile to use")
    parser.add_argument("--model", default=None, help="Specific model ID to test")
    
    args = parser.parse_args()
    
    test_inference_profiles(aws_profile=args.profile, model_id=args.model)
